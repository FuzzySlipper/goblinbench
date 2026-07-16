# Plugin hook context and concurrent gateway runs

Use this reference when adding Hermes plugin hooks that observe tool calls, lifecycle events, or gateway processing while multiple sessions may be active.

## Core lesson

Gateway platform adapters can spawn background processing tasks and continue accepting/starting other deliveries. A plugin hook that stores active session/delivery context in process-global mutable state (`os.environ`, module globals without per-task keys, singleton fields) can misattribute events across concurrent sessions.

Prefer `contextvars.ContextVar` for per-task context that follows async execution. Use explicit keyed maps only when the hook receives stable IDs in every call and cleanup is deterministic.

## Pattern

```python
import contextvars

_ACTIVE_CONTEXT: contextvars.ContextVar[dict[str, object]] = contextvars.ContextVar(
    "plugin_active_context",
    default={},
)

async def on_processing_start(event):
    _ACTIVE_CONTEXT.set({
        "session_key": event.source.session_key,
        "delivery_id": event.raw_message.get("delivery_request_id"),
    })

async def on_processing_complete(event, outcome):
    try:
        ...
    finally:
        _ACTIVE_CONTEXT.set({})

def on_pre_tool_call(**kwargs):
    context = _ACTIVE_CONTEXT.get({})
    if not context:
        return
    ...
```

## Pitfalls

- Do not make `os.environ` the primary in-process context channel. It is process-global and unsafe for concurrent gateway deliveries. If an env var is retained for compatibility, treat it as a fallback only.
- Validate key aliases through the real emitter path, not only by checking the context-binding payload. A mismatch such as storing `hermesSessionKey` but reading only `sessionKey` can silently drop attribution.
- Hook failures should be isolated unless the hook intentionally enforces a blocking policy. Observability hooks should catch/log exceptions so tool execution and final responses continue.
- Bound and redact hook payloads before they leave the process. Tool arguments can contain command bodies, headers, tokens, and user data.
- Tests should cover concurrent contexts or at least two interleaved contexts so process-global state regressions are caught.

## Review checklist

- Does every callback receive context from a task-local source or stable per-call IDs?
- Is cleanup in a `finally` block?
- Are errors swallowed/logged for observer-only hooks?
- Are secrets redacted recursively and previews truncated?
- Does a test exercise the actual emitted payload, including session/delivery IDs?
