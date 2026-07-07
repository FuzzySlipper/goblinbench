"""OpenAI-compatible multimodal vision runner — port of VisionCandidateRunner.cs.

Reads image paths from ``scenario.input.image_paths``, encodes them as base64
data URLs, and calls ``/chat/completions`` with a multimodal message. The system
prompt instructs the model to return the structured JSON the
``VisionCorrectnessScorer`` expects.

Activated by ``cli_command = "vision-openai"`` (any candidate kind — mirrors C#,
which keys only on the cli_command, not the kind).
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso
from . import _openai

_VISION_SYSTEM_PROMPT = """You are a vision analysis assistant. Analyze the provided screenshot(s) carefully and answer the question.

Always respond with a JSON object matching this exact schema:
{
  "elements_found": ["list", "of", "ui", "elements", "you", "can", "see"],
  "answer": "direct answer to the question asked",
  "confidence": 0.0,
  "hallucination_risk": "low|medium|high",
  "suggested_action": "next action to take, or null if not applicable",
  "actionability": 0.0
}

Rules:
- elements_found: list only elements you can actually see. Do NOT invent elements.
- answer: be specific and direct. Reference what you actually observe.
- confidence: your confidence in the analysis (0.0 = uncertain, 1.0 = certain).
- hallucination_risk: rate your own risk of confabulating. "high" if uncertain about details.
- suggested_action: the most likely next user interaction, or null if not asked.
- actionability: how actionable your analysis is for the caller (0.0 = no action needed, 1.0 = clear next step).

Output ONLY the JSON object. Do not wrap it in markdown code blocks or add explanation."""


class VisionCandidateRunner:
    name = "vision-openai"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        # C# keys only on cli_command (not kind) — so any candidate with this
        # cli_command routes here regardless of Kind.
        return (candidate.cli_command or "").strip().lower() == "vision-openai"

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_perf = time.perf_counter()
        base_url = candidate.base_url or candidate.endpoint or "https://api.openai.com/v1"
        model = candidate.model or "gpt-4o"
        api_key = _openai.resolve_api_key(candidate)
        req_timeout = timeout if timeout is not None else 300

        trace: list[TraceEvent] = [
            TraceEvent(timestamp=now_iso(), event="vision.runner.started",
                       data={"model": model, "base_url": base_url})
        ]
        model_identity = ModelIdentity(
            model=model, provider=candidate.provider, base_url=base_url,
            display_name=f"{candidate.provider}/{model}",
        )

        try:
            image_parts, image_count = _build_image_parts(scenario, context, trace)
            prompt = _get_prompt(scenario)
            messages = _build_messages(prompt, image_parts, candidate, scenario)
            request_body = {
                "model": model,
                "messages": messages,
                "temperature": _openai.config_double(candidate, "temperature", 0.2),
                "max_tokens": _openai.config_int(candidate, "max_tokens", 2048),
            }
            trace.append(TraceEvent(
                timestamp=now_iso(), event="vision.request.sent",
                data={"image_count": image_count, "prompt_length": len(prompt)},
            ))

            resp = _openai.post_chat_completions(base_url, request_body, api_key, req_timeout)

            trace.append(TraceEvent(
                timestamp=now_iso(), event="vision.response.received",
                data={"status_code": resp.status_code},
            ))

            parsed_output: dict[str, Any] | None = None
            model_text: str | None = None
            error: str | None = None

            if resp.error:
                error = resp.error
            elif not resp.success:
                error = f"HTTP {resp.status_code}: {(resp.body or '')[:500]}"
            else:
                doc = json.loads(resp.body)
                model_text = _openai.extract_message_content(_openai.extract_message(doc))
                if model_text is not None:
                    parsed_output = _openai.extract_json_object(model_text)

            _write_artifacts(candidate, context, resp.body or "", parsed_output)

            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=model_identity,
                success=(resp.success and not resp.error),
                error=error,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                raw_response=model_text if model_text is not None else (resp.body or ""),
                parsed_response=parsed_output,
                output=parsed_output,
                trace=trace,
                artifact_directory=context.candidate_artifacts_directory(candidate.id),
            )
        except Exception as ex:  # noqa: BLE001 — runner isolation mirrors C#
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=model_identity,
                success=False,
                error=_openai.redact_secrets(str(ex)),
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                trace=trace,
                artifact_directory=context.candidate_artifacts_directory(candidate.id),
            )


def _build_image_parts(
    scenario: Scenario, context: RunContext, trace: list[TraceEvent]
) -> tuple[list[dict[str, Any]], int]:
    """Resolve image paths (relative to repo root) → base64 data-url content parts."""
    parts: list[dict[str, Any]] = []
    paths_obj = scenario.input.get("image_paths")
    if not isinstance(paths_obj, list):
        return parts, 0
    # Repo root = parent of runs/.
    runs_parent = os.path.dirname(context.runs_root) if context.runs_root else context.runs_root or ""
    for rel in paths_obj:
        if not isinstance(rel, str):
            continue
        abs_path = rel if os.path.isabs(rel) else os.path.join(runs_parent, rel)
        if not os.path.isfile(abs_path):
            trace.append(TraceEvent(
                timestamp=now_iso(), event="vision.image.not_found", data={"path": rel}
            ))
            continue
        with open(abs_path, "rb") as f:
            data = f.read()
        mime = "image/png" if abs_path.lower().endswith(".png") else "image/jpeg"
        b64 = base64.b64encode(data).decode("ascii")
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"},
        })
        trace.append(TraceEvent(
            timestamp=now_iso(), event="vision.image.encoded",
            data={"path": rel, "bytes": len(data)},
        ))
    return parts, len(parts)


def _get_prompt(scenario: Scenario) -> str:
    p = scenario.input.get("prompt")
    if isinstance(p, str):
        return p
    return scenario.description


def _scenario_system_prompt(scenario: Scenario, candidate: CandidateConfig) -> str:
    """Resolve the prompt contract for a vision scenario.

    Existing UI scenarios use the candidate/default prompt. Richer visual-inspect
    probes (for example chaotic-description scenarios) can provide an
    ``input.system_prompt`` or ``input.response_schema`` block so one candidate
    can run both old UI verdict tests and new description-quality tests without
    duplicating candidate entries just to swap schemas.
    """
    explicit = scenario.input.get("system_prompt")
    if isinstance(explicit, str) and explicit.strip():
        return explicit

    schema = scenario.input.get("response_schema")
    if schema == "vision_description_v1":
        return _VISION_DESCRIPTION_SYSTEM_PROMPT

    return candidate.system_prompt or _VISION_SYSTEM_PROMPT


_VISION_DESCRIPTION_SYSTEM_PROMPT = """You are a careful visual description assistant for visual-inspect benchmark scenarios.

Analyze the provided screenshot(s) and produce a concrete, region-aware description. If the image is cluttered or ambiguous, still make a serious attempt, but mark uncertain details as uncertain instead of inventing specifics.

Always respond with a JSON object matching this exact schema:
{
  "scene_summary": "one or two sentence overview of the image",
  "salient_regions": [{"region": "upper left|upper right|center|lower left|lower right|other", "description": "what is visible there"}],
  "objects_and_entities": [{"label": "visible object or UI element", "location": "where it appears", "attributes": ["concrete visible attributes"]}],
  "relationships": ["spatial relationships, overlaps, containment, adjacency, or UI state relationships"],
  "text_observed": ["visible text snippets only when legible"],
  "uncertainties": ["ambiguous or occluded details"],
  "answer": "direct answer to the scenario prompt",
  "confidence": 0.0,
  "hallucination_risk": "low|medium|high"
}

Rules:
- Be specific: name visible objects, UI regions, text, and locations when possible.
- Do not give only a generic summary like "a cluttered image with many objects".
- Do not claim absent target objects just because the prompt mentions them.
- Use uncertainties for occluded, blurry, tiny, or ambiguous details.
- Output ONLY the JSON object. Do not wrap it in markdown code blocks or add explanation."""


def _build_messages(
    prompt: str, image_parts: list[dict[str, Any]], candidate: CandidateConfig, scenario: Scenario
) -> list[dict[str, Any]]:
    system_prompt = _scenario_system_prompt(scenario, candidate)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}] + image_parts
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]


def _write_artifacts(
    candidate: CandidateConfig, context: RunContext, raw_response: str, parsed: dict[str, Any] | None
) -> None:
    artifact_dir = context.candidate_artifacts_directory(candidate.id)
    os.makedirs(artifact_dir, exist_ok=True)
    output_path = context.candidate_output_path(candidate.id)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if raw_response:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(raw_response)
    if parsed is not None:
        with open(os.path.join(artifact_dir, "vision_analysis.json"), "w", encoding="utf-8") as f:
            f.write(dumps(parsed))
