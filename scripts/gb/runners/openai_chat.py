"""OpenAI-compatible chat completions runner — port of OpenAiChatRunner.cs.

Calls an OpenAI-compatible ``/chat/completions`` endpoint, records latency,
raw/parsed response, and errors. Secrets are never written to run artifacts
(redacted in-memory before serialization).

Uses only the Python stdlib (``urllib``) so the runner stays zero-dependency —
no virtualenv required to run the bench.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso

_SECRET_PATTERNS = (
    "api_key", "api-key", "Authorization", "Bearer",
    "sk-", "sk-ant-", "hf_", "x-api-key",
)

_BOUNDARY = frozenset(" \t\n\r,\",}]")  # chars that end a secret value

# cli_command / config.runner values handled by specialized OpenAiModel runners
# (OpenAiMcpToolUseRunner, OpenAiFuzzyAgentRunner, OpenAiMcpSessionRunner,
# VisionCandidateRunner). The plain chat runner must NOT claim these — they are
# Milestone-3 ports. Until ported, these candidates get a clean "SKIP (no runner)"
# rather than being mishandled as plain chat. In C#, disambiguation is by
# registration order (specialized runners precede OpenAiChatRunner); here we make
# the predicate explicit so order alone can't cause silent mis-dispatch.
_SPECIALIZED_OPENAI_DISCRIMINATORS = {
    "mcp-openai-tool-use",
    "fuzzy-openai",
    "mcp-openai-session",
    "vision-openai",
}


class OpenAiChatRunner:
    name = "openai-chat"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        if candidate.kind is None or candidate.kind.value != "OpenAiModel":
            return False
        discriminator = (candidate.cli_command or "").strip().lower()
        if not discriminator:
            # C# specialized runners also match config.runner; honor that here too.
            discriminator = str(candidate.config.get("runner") or "").strip().lower()
        if discriminator in _SPECIALIZED_OPENAI_DISCRIMINATORS:
            return False
        return True

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_at = now_iso()
        started_perf = time.perf_counter()
        trace: list[TraceEvent] = []

        api_key = _resolve_api_key(candidate)
        base_url = candidate.base_url or candidate.endpoint or "https://api.openai.com/v1"
        model = candidate.model or "gpt-4o"

        messages = _build_messages(scenario, candidate)
        request_body = {
            "model": model,
            "messages": messages,
            "max_tokens": _config_int(candidate, "max_tokens", 4096),
        }
        reasoning_effort = _config_string(candidate, "reasoning_effort")
        if reasoning_effort:
            request_body["reasoning_effort"] = reasoning_effort
        if not reasoning_effort or _config_bool(candidate, "include_temperature_with_reasoning_effort", False):
            request_body["temperature"] = _config_double(candidate, "temperature", 0.7)
        chat_template_kwargs = candidate.config.get("chat_template_kwargs")
        if isinstance(chat_template_kwargs, dict):
            request_body["chat_template_kwargs"] = chat_template_kwargs
        # Some OpenAI-compatible local servers expose provider/model-specific
        # knobs at the top level (for example llama.cpp/Lemonade
        # chat_template_kwargs to disable/enable thinking mode). Keep the generic
        # chat runner extensible without adding one-off fields for every backend.
        # request_overrides is applied last so experiments can still override any
        # first-class convenience field above.
        overrides = candidate.config.get("request_overrides")
        if isinstance(overrides, dict):
            request_body.update(overrides)
        request_json = json.dumps(request_body)

        trace.append(TraceEvent(
            timestamp=now_iso(),
            event="openai.request.built",
            data={"model": model, "base_url": base_url, "message_count": len(messages)},
        ))

        # Default timeout mirrors the C# 300s; candidate/scenario may override.
        req_timeout = timeout if timeout is not None else 300

        model_identity = ModelIdentity(
            model=model,
            provider=candidate.provider,
            base_url=base_url,
            display_name=f"{candidate.provider}/{model}",
        )

        try:
            url = base_url.rstrip("/") + "/chat/completions"
            req = urllib.request.Request(
                url,
                data=request_json.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")

            trace.append(TraceEvent(timestamp=now_iso(), event="openai.request.sent"))

            try:
                with urllib.request.urlopen(req, timeout=req_timeout) as resp:
                    status_code = resp.getcode()
                    raw_bytes = resp.read()
            except urllib.error.HTTPError as he:
                # HTTP error: read body for the error message, treat as non-success.
                status_code = he.code
                raw_bytes = he.read()
            except (urllib.error.URLError, TimeoutError, OSError) as ex:
                # Network/connection/timeout error.
                trace.append(TraceEvent(
                    timestamp=now_iso(), event="openai.request.failed",
                    data={"error": str(ex)}))
                duration_ms = int((time.perf_counter() - started_perf) * 1000)
                return CandidateResult(
                    candidate_id=candidate.id,
                    candidate_name=candidate.name,
                    candidate_kind=candidate.kind,
                    model_identity=model_identity,
                    success=False,
                    error=redact_secrets(str(ex)),
                    duration_ms=duration_ms,
                    trace=trace,
                    artifact_directory=context.candidate_artifacts_directory(candidate.id),
                )

            raw_response = redact_secrets(raw_bytes.decode("utf-8", errors="replace")) or ""
            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="openai.response.received",
                data={"status_code": status_code, "content_length": len(raw_response)},
            ))

            success = 200 <= status_code < 300
            parsed_response: Any = None
            model_text: str | None = None
            error: str | None = None

            if success:
                model_text = _extract_model_text(raw_response)
                if model_text is not None:
                    parsed_response = _try_extract_json(model_text)
                else:
                    parsed_response = _try_parse_json_object(raw_response)
            else:
                error = f"HTTP {status_code}: {raw_response[:500]}"

            _write_artifacts(candidate, context, raw_response, parsed_response, error)
            duration_ms = int((time.perf_counter() - started_perf) * 1000)

            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=model_identity,
                success=success,
                error=error,
                duration_ms=duration_ms,
                raw_response=model_text if model_text is not None else raw_response,
                parsed_response=parsed_response,
                output={"model": model, "status": "ok" if success else "error"},
                trace=trace,
                artifact_directory=context.candidate_artifacts_directory(candidate.id),
            )
        except Exception as ex:  # noqa: BLE001 — runner isolation mirrors C#
            duration_ms = int((time.perf_counter() - started_perf) * 1000)
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=model_identity,
                success=False,
                error=redact_secrets(str(ex)),
                duration_ms=duration_ms,
                trace=trace,
                artifact_directory=context.candidate_artifacts_directory(candidate.id),
            )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _resolve_api_key(candidate: CandidateConfig) -> str | None:
    if candidate.api_key:
        return candidate.api_key
    if candidate.api_key_env:
        val = os.environ.get(candidate.api_key_env)
        if val:
            return val
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("GOBLINBENCH_OPENAI_API_KEY")


def _build_messages(scenario: Scenario, candidate: CandidateConfig) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if candidate.system_prompt:
        messages.append({"role": "system", "content": candidate.system_prompt})

    prompt = scenario.input.get("prompt")
    if isinstance(prompt, str):
        messages.append({"role": "user", "content": prompt})
    elif scenario.input:
        messages.append({"role": "user", "content": json.dumps(scenario.input, ensure_ascii=False)})
    else:
        messages.append({"role": "user", "content": scenario.description})
    return messages


def _config_double(candidate: CandidateConfig, key: str, default: float) -> float:
    v = candidate.config.get(key)
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    return default


def _config_int(candidate: CandidateConfig, key: str, default: int) -> int:
    v = candidate.config.get(key)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if v is not None:
        try:
            return int(v)
        except (TypeError, ValueError):
            pass
    return default


def _config_bool(candidate: CandidateConfig, key: str, default: bool) -> bool:
    v = candidate.config.get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _config_string(candidate: CandidateConfig, key: str) -> str | None:
    v = candidate.config.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _extract_model_text(raw_api_response: str) -> str | None:
    try:
        doc = json.loads(raw_api_response)
    except (json.JSONDecodeError, ValueError):
        return None
    choices = doc.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    return content if isinstance(content, str) else None


def _try_extract_json(model_text: str | None) -> Any:
    """Strip markdown fences and extract the first JSON object/array."""
    if not model_text:
        return None
    t = model_text.strip()
    if t.startswith("```"):
        fence_end = t.find("\n")
        close_fence = t.rfind("```")
        if fence_end >= 0 and close_fence > fence_end:
            t = t[fence_end + 1:close_fence].strip()
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _try_parse_json_object(text: str) -> Any:
    try:
        v = json.loads(text)
        return v
    except (json.JSONDecodeError, ValueError):
        return None


def _write_artifacts(
    candidate: CandidateConfig,
    context: RunContext,
    raw_response: str,
    parsed_response: Any,
    error: str | None,
) -> None:
    artifact_dir = context.candidate_artifacts_directory(candidate.id)
    os.makedirs(artifact_dir, exist_ok=True)

    # Raw response (already redacted) → output.json.
    if raw_response:
        output_path = context.candidate_output_path(candidate.id)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(raw_response)

    # Parsed response.
    if parsed_response is not None:
        parsed_path = os.path.join(artifact_dir, "parsed_response.json")
        with open(parsed_path, "w", encoding="utf-8") as f:
            f.write(dumps(parsed_response))

    # Error.
    if error:
        error_path = os.path.join(artifact_dir, "error.txt")
        with open(error_path, "w", encoding="utf-8") as f:
            f.write(redact_secrets(error))


def redact_secrets(text: str | None) -> str | None:
    """Port of C# RedactSecrets: redact known secret patterns before writing artifacts."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        idx = text.lower().find(pattern.lower())
        while idx >= 0:
            end = idx + len(pattern)
            # Skip past optional ':' / '=' / spaces.
            while end < len(text) and text[end] in ":= ":
                end += 1
            value_start = end
            while end < len(text) and text[end] not in _BOUNDARY:
                end += 1
            if value_start < end:
                text = text[:value_start] + "[REDACTED]" + text[end:]
            idx = text.lower().find(pattern.lower(), value_start)
    return text
