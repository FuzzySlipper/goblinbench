"""Shared OpenAI-compatible HTTP + parsing helpers.

Extracted from the C# runners (OpenAiChatRunner, OpenAiMcpToolUseRunner,
OpenAiFuzzyAgentRunner, OpenAiMcpSessionRunner, VisionCandidateRunner), which
each carry near-identical copies of: API-key resolution, config value
extraction, the /chat/completions POST, secret redaction, and choices[0]
message parsing. Centralizing them keeps the four specialized runners (and the
existing chat runner) faithful and drift-free.

All helpers are stdlib-only (urllib + json) — no requests/httpx dependency.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..models import CandidateConfig

_SECRET_PATTERNS = (
    "api_key", "api-key", "Authorization", "Bearer",
    "sk-", "sk-ant-", "hf_", "x-api-key",
)

_BOUNDARY = frozenset(" \t\n\r,\",}]")  # chars that end a secret value


# ── Secret redaction (port of OpenAiChatRunner.RedactSecrets) ──────────────


def redact_secrets(text: str | None) -> str | None:
    """Redact known secret patterns before writing to artifacts/traces."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        idx = text.lower().find(pattern.lower())
        while idx >= 0:
            end = idx + len(pattern)
            while end < len(text) and text[end] in ":= ":
                end += 1
            value_start = end
            while end < len(text) and text[end] not in _BOUNDARY:
                end += 1
            if value_start < end:
                text = text[:value_start] + "[REDACTED]" + text[end:]
            idx = text.lower().find(pattern.lower(), value_start)
    return text


# ── API key resolution (port of the per-runner ResolveApiKey) ──────────────


def resolve_api_key(candidate: CandidateConfig) -> str | None:
    """Resolve the API key: explicit → ApiKeyEnv → config.api_key_env → common env."""
    if candidate.api_key:
        return candidate.api_key
    if candidate.api_key_env:
        v = os.environ.get(candidate.api_key_env)
        if v:
            return v
    config_env = config_string(candidate, "api_key_env")
    if config_env:
        v = os.environ.get(config_env)
        if v:
            return v
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("GOBLINBENCH_OPENAI_API_KEY")


# ── Config extraction (port of the per-runner ConfigString/Int/Double) ─────


def config_string(candidate: CandidateConfig, key: str) -> str | None:
    v = candidate.config.get(key)
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return str(v)


def config_int(candidate: CandidateConfig, key: str, default: int) -> int:
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


def config_double(candidate: CandidateConfig, key: str, default: float) -> float:
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


# ── HTTP (port of the per-runner POST + redact cycle) ─────────────────────


class HttpResponse:
    """Lightweight HTTP response envelope. status_code 0 + error set on transport failure."""

    __slots__ = ("status_code", "body", "error")

    def __init__(self, status_code: int, body: str = "", error: str | None = None):
        self.status_code = status_code
        self.body = body
        self.error = error

    @property
    def success(self) -> bool:
        return 200 <= self.status_code < 300


def post_chat_completions(
    base_url: str,
    request_body: dict[str, Any],
    api_key: str | None,
    timeout: float = 300,
) -> HttpResponse:
    """POST a chat-completions request body, redact secrets in the response, return envelope.

    Network/connection errors are caught and returned as HttpResponse(0, error=...)
    so the caller can format them as a CandidateResult.failure without try/except
    plumbing — matching the C# behavior where each runner wraps the whole call.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(request_body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return HttpResponse(resp.getcode(), redact_secrets(body) or "")
    except urllib.error.HTTPError as he:
        # HTTP error: keep the body so the caller can surface it.
        body = ""
        try:
            body = he.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        return HttpResponse(he.code, redact_secrets(body) or "")
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        return HttpResponse(0, error=str(ex))


# ── Response parsing (port of ExtractMessage/Content/ToolCalls) ────────────


def extract_message(root: dict[str, Any]) -> dict[str, Any]:
    """Return choices[0].message. Raises if the envelope is malformed (mirrors C#)."""
    choices = root.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI-compatible response did not include choices[0].message.")
    msg = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(msg, dict):
        raise ValueError("OpenAI-compatible response did not include choices[0].message.")
    return msg


def extract_message_content(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    return content if isinstance(content, str) else None


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls")
    return list(calls) if isinstance(calls, list) else []


def extract_tool_call_id(tool_call: dict[str, Any]) -> str:
    """Port of C# ExtractToolCallId — falls back to a fresh uuid hex if missing."""
    import uuid
    tid = tool_call.get("id")
    return tid if isinstance(tid, str) and tid else uuid.uuid4().hex


def extract_tool_name(tool_call: dict[str, Any]) -> str:
    fn = tool_call.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        if isinstance(name, str):
            return name
    direct = tool_call.get("name")
    return direct if isinstance(direct, str) else ""


def extract_tool_arguments(tool_call: dict[str, Any]) -> Any:
    """Port of C# ExtractToolArguments: function.arguments is a JSON string in the
    OpenAI tool-call schema; parse it. Malformed → {"_raw": raw}."""
    fn = tool_call.get("function")
    if not isinstance(fn, dict):
        return {}
    args = fn.get("arguments")
    if isinstance(args, str):
        raw = args
        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {"_raw": raw}
    return args if isinstance(args, (dict, list)) else {}


# ── JSON extraction from model text (markdown fences + brace scraping) ─────


def extract_json_object(model_text: str | None) -> dict[str, Any] | None:
    """Strip markdown fences and extract the first JSON object. Returns None if not parseable."""
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
            v = json.loads(t[start:end + 1])
            return v if isinstance(v, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def extract_any_json(model_text: str | None) -> Any:
    """Like extract_json_object but returns objects/arrays/primitives (or None)."""
    if not model_text:
        return None
    t = model_text.strip()
    if t.startswith("```"):
        fence_end = t.find("\n")
        close_fence = t.rfind("```")
        if fence_end >= 0 and close_fence > fence_end:
            t = t[fence_end + 1:close_fence].strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        end = t.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(t[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    return None


# ── Scenario prompt helpers ────────────────────────────────────────────────


def scenario_prompt(scenario_input: dict[str, Any], description: str) -> str:
    """Read scenario.input.prompt; fall back to description (port of GetScenarioPrompt)."""
    p = scenario_input.get("prompt")
    if isinstance(p, str):
        return p
    return description


def get_string_from_input(scenario_input: dict[str, Any], key: str) -> str:
    v = scenario_input.get(key)
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


def to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Map a fake-mcp tool ({name,description,input_schema}) → OpenAI tools[] entry.

    Shared by the MCP tool-use + MCP session runners (C# ToOpenAiTool).
    """
    name = tool.get("name") or "unknown_fake_tool"
    description = tool.get("description") or ""
    parameters = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {"type": "object"}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def execute_fake_tool(
    tool_name: str,
    arguments: dict[str, Any],
    scripted_calls: list[dict[str, Any]],
    used_indexes: set[int],
    tool_specs: list[dict[str, Any]] | None = None,
) -> Any:
    """Execute a scenario tool against one shared contract.

    Tool schema validation occurs before canned-result matching. A tool that is
    advertised but intentionally has no fixture behavior is explicitly
    unavailable; it never receives a misleading synthetic success.
    """
    tool_specs = tool_specs or []
    known_tools = {str(t.get("name")) for t in tool_specs if isinstance(t, dict) and t.get("name")}
    if tool_specs and tool_name not in known_tools:
        return {"ok": False, "error": f"unknown fake tool: {tool_name}", "retryable": False}

    schema_error = validate_fake_tool_arguments(tool_name, arguments, tool_specs)
    if schema_error:
        return {"ok": False, "error": f"validation failed for fake tool: {tool_name}: {schema_error}", "retryable": True}

    known_scripted_names = {str(c.get("tool")) for c in scripted_calls if c.get("tool")}
    for i, call in enumerate(scripted_calls):
        if i in used_indexes or str(call.get("tool")) != tool_name:
            continue
        expected = call.get("arguments")
        if isinstance(expected, dict) and not _fake_tool_arguments_match(expected, arguments):
            return {
                "ok": False,
                "error": f"validation failed for fake tool: {tool_name}",
                "retryable": True,
            }
        used_indexes.add(i)
        if "result" in call:
            return call["result"]
        return {"ok": True}
    if tool_name in known_scripted_names:
        return {"ok": True, "note": "tool called more times than canned results were provided"}
    if tool_name in known_tools:
        return {"ok": False, "error": f"unavailable fake tool: {tool_name}", "retryable": False}
    return {"ok": False, "error": f"unknown or unscripted fake tool: {tool_name}", "retryable": False}


def validate_fake_tool_arguments(
    tool_name: str, arguments: dict[str, Any], tool_specs: list[dict[str, Any]]
) -> str | None:
    """Validate the portable JSON-Schema subset used by GoblinBench fixtures."""
    if not tool_specs:
        return None
    tool = next((t for t in tool_specs if isinstance(t, dict) and t.get("name") == tool_name), None)
    if tool is None:
        return "unknown tool"
    schema = tool.get("input_schema")
    if not isinstance(schema, dict):
        return None
    if schema.get("type") == "object" and not isinstance(arguments, dict):
        return "arguments must be an object"
    required = schema.get("required", [])
    if isinstance(required, list):
        missing = [str(key) for key in required if key not in arguments]
        if missing:
            return f"missing required field(s): {', '.join(missing)}"
    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        if schema.get("additionalProperties") is False:
            unexpected = sorted(str(key) for key in arguments if key not in properties)
            if unexpected:
                return f"unexpected field(s): {', '.join(unexpected)}"
        for key, value in arguments.items():
            prop = properties.get(key)
            if not isinstance(prop, dict):
                continue
            expected_type = prop.get("type")
            if expected_type and not _json_schema_type_matches(str(expected_type), value):
                return f"field '{key}' must be {expected_type}"
            choices = prop.get("enum")
            if isinstance(choices, list) and value not in choices:
                return f"field '{key}' must be one of {choices}"
            if isinstance(value, str) and isinstance(prop.get("minLength"), int) and len(value) < prop["minLength"]:
                return f"field '{key}' must have at least {prop['minLength']} character(s)"
    return None


def _json_schema_type_matches(expected_type: str, value: Any) -> bool:
    return {
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
    }.get(expected_type, True)


def _fake_tool_arguments_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Match scenario-owned argument values without freezing free-text safe effects."""
    return all(key in actual and _fake_tool_value_matches(value, actual[key]) for key, value in expected.items())


def _fake_tool_value_matches(expected: Any, actual: Any) -> bool:
    if expected == "$any_nonempty_string":
        return isinstance(actual, str) and bool(actual.strip())
    return expected == actual
