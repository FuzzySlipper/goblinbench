"""OpenAI-compatible MCP tool-use runner — port of OpenAiMcpToolUseRunner.cs.

Multi-round tool-call loop against an OpenAI /chat/completions endpoint. Maps
scenario-owned ``input.fake_mcp.tools`` to the OpenAI tool schema, executes
requested tool calls against the scenario's canned (``scripted_tool_calls``)
results, and writes the artifact shape consumed by ``McpToolUseScorer``.

Claims ``OpenAiModel`` candidates whose ``cli_command`` or ``config.runner``
is ``mcp-openai-tool-use``.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..serialize import dumps, now_iso
from . import _openai


class OpenAiMcpToolUseRunner:
    name = "mcp-openai-tool-use"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        if candidate.kind is None or candidate.kind.value != "OpenAiModel":
            return False
        disc = (candidate.cli_command or "").strip().lower()
        if not disc:
            disc = str(candidate.config.get("runner") or "").strip().lower()
        return disc == "mcp-openai-tool-use"

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_perf = time.perf_counter()
        artifact_dir = context.candidate_artifacts_directory(candidate.id)
        os.makedirs(artifact_dir, exist_ok=True)

        base_url = candidate.base_url or candidate.endpoint or "https://api.openai.com/v1"
        model = candidate.model or "gpt-4o"
        api_key = _openai.resolve_api_key(candidate)
        req_timeout = timeout if timeout is not None else 300

        trace: list[TraceEvent] = [
            TraceEvent(timestamp=now_iso(), event="mcp_openai.started", data={"scenario": scenario.id})
        ]
        tool_call_records: list[dict[str, Any]] = []
        bypass_attempts: list[dict[str, Any]] = []
        messages = _build_initial_messages(scenario, candidate)
        fake_tools = _get_fake_tools(scenario)
        scripted_calls = _get_scripted_tool_calls(scenario)
        used_scripted_indexes: set[int] = set()
        final_response = ""
        error: str | None = None
        success = False

        try:
            if not fake_tools:
                raise ValueError("MCP tool-use scenario has no input.fake_mcp.tools entries.")

            max_tool_rounds = max(1, _openai.config_int(candidate, "max_tool_rounds", 6))
            for round_idx in range(max_tool_rounds):
                request_body = _build_request_body(candidate, model, messages, fake_tools)
                request_json = json.dumps(request_body)
                _write(artifact_dir, f"request_round_{round_idx + 1}.json", request_json)

                trace.append(TraceEvent(
                    timestamp=now_iso(), event="mcp_openai.request.sent",
                    data={"round": round_idx + 1, "model": model, "tool_count": len(fake_tools)},
                ))

                resp = _openai.post_chat_completions(base_url, request_body, api_key, req_timeout)
                _write(artifact_dir, f"api_response_round_{round_idx + 1}.json", resp.body)

                if resp.error:
                    error = resp.error
                    break

                trace.append(TraceEvent(
                    timestamp=now_iso(), event="mcp_openai.response.received",
                    data={"round": round_idx + 1, "status_code": resp.status_code,
                          "content_length": len(resp.body or "")},
                ))

                if not resp.success:
                    error = f"HTTP {resp.status_code}: {(resp.body or '')[:500]}"
                    break

                doc = json.loads(resp.body)
                message = _openai.extract_message(doc)
                content = _openai.extract_message_content(message)
                if content:
                    final_response = content
                tool_calls = _openai.extract_tool_calls(message)

                if not tool_calls:
                    success = True
                    break

                messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                })

                for tool_call in tool_calls:
                    call_id = _openai.extract_tool_call_id(tool_call)
                    tool_name = _openai.extract_tool_name(tool_call)
                    arguments = _openai.extract_tool_arguments(tool_call)
                    result = _openai.execute_fake_tool(
                        tool_name, arguments, scripted_calls, used_scripted_indexes, fake_tools
                    )
                    record = {
                        "tool": tool_name,
                        "arguments": arguments,
                        "result": result,
                        "tool_call_id": call_id,
                        "order": len(tool_call_records) + 1,
                    }
                    tool_call_records.append(record)
                    trace.append(TraceEvent(
                        timestamp=now_iso(), event="mcp_openai.tool_called", data=record,
                    ))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": tool_name,
                        "content": json.dumps(result),
                    })

            if not success and error is None:
                error = "Model did not produce a final response before max_tool_rounds was reached."
        except Exception as ex:  # noqa: BLE001 — runner isolation mirrors C#
            error = _openai.redact_secrets(str(ex))

        if not final_response.strip() and error:
            final_response = error

        output = {
            "tool_calls": tool_call_records,
            "bypass_attempts": bypass_attempts,
            "final_response": final_response,
        }
        raw_output = dumps(output, indent=2)

        _write(artifact_dir, "tool_calls.json", dumps(tool_call_records))
        _write(artifact_dir, "bypass_attempts.json", dumps(bypass_attempts))
        _write(artifact_dir, "final_response.txt", final_response)
        _write(artifact_dir, "chat_transcript.json", dumps(messages))
        _write_output(context, candidate, raw_output)
        if error:
            _write(artifact_dir, "error.txt", error)

        trace.append(TraceEvent(
            timestamp=now_iso(),
            event="mcp_openai.completed" if success else "mcp_openai.failed",
            data={
                "tool_call_count": len(tool_call_records),
                "bypass_attempt_count": len(bypass_attempts),
                "artifact_dir": artifact_dir,
                "error": error,
            },
        ))

        return CandidateResult(
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            candidate_kind=candidate.kind,
            model_identity=ModelIdentity(
                model=model, provider=candidate.provider, base_url=base_url,
                display_name=f"{candidate.provider}/{model} MCP tools",
            ),
            success=success,
            error=error,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            raw_response=raw_output,
            parsed_response=output,
            output=output,
            trace=trace,
            artifact_directory=artifact_dir,
        )


# ── Helpers ────────────────────────────────────────────────────────────────


def _build_request_body(
    candidate: CandidateConfig, model: str, messages: list[dict[str, Any]], fake_tools: list[dict[str, Any]]
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": [_openai.to_openai_tool(t) for t in fake_tools],
        "tool_choice": _openai.config_string(candidate, "tool_choice") or "auto",
        "max_tokens": _openai.config_int(candidate, "max_tokens", 4096),
    }
    # Only include temperature if no reasoning_effort is set; some reasoning
    # models reject temperature != 1 when reasoning_effort is present.
    reasoning_effort = _openai.config_string(candidate, "reasoning_effort")
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    else:
        body["temperature"] = _openai.config_double(candidate, "temperature", 0.2)
    return body


def _build_initial_messages(scenario: Scenario, candidate: CandidateConfig) -> list[dict[str, Any]]:
    system = candidate.system_prompt or (
        "You are evaluating fake MCP tool use. Use only the provided tools when a tool is needed. "
        "Do not claim to perform real-world side effects. After using tools, provide a concise "
        "final answer grounded in tool results."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _openai.scenario_prompt(scenario.input, scenario.description)},
    ]


def _get_fake_tools(scenario: Scenario) -> list[dict[str, Any]]:
    fake_mcp = scenario.input.get("fake_mcp")
    if not isinstance(fake_mcp, dict):
        return []
    tools = fake_mcp.get("tools")
    return [t for t in tools if isinstance(t, dict)] if isinstance(tools, list) else []


def _get_scripted_tool_calls(scenario: Scenario) -> list[dict[str, Any]]:
    calls = scenario.input.get("scripted_tool_calls")
    return [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []


def _write(artifact_dir: str, name: str, content: str) -> None:
    with open(os.path.join(artifact_dir, name), "w", encoding="utf-8") as f:
        f.write(content)


def _write_output(context: RunContext, candidate: CandidateConfig, content: str) -> None:
    output_path = context.candidate_output_path(candidate.id)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
