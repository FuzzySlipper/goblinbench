# App-server protocol and scoring safety

## Bounded event streams are necessary but not sufficient

For WebSocket/JSON-RPC coding-agent runners, keep three independent bounds:

- maximum raw-event artifact bytes (stream JSONL to disk; stop recording payloads after a marker),
- maximum buffered notification count/bytes,
- maximum individual WebSocket frame size and accumulated assistant text.

Use separate short acknowledgement deadlines for `thread/start` and `turn/start`, in addition to the overall turn-completion deadline. On a limit/deadline breach, interrupt if possible, retain a partial workspace diff and bounded artifacts, and classify it as runner/substrate failure.

## Critical request-loop rule

A request waiting for its JSON-RPC response **must read directly from the socket**, not via the public `receive()` method when that method first drains preserved notifications.

Otherwise the request loop can pop one queued notification, record it, put it back into the queue, and repeat forever. If raw events are retained in memory this becomes an OOM; even with capped event artifacts it is a CPU/time spin. Implement two paths:

- `receive()` for turn processing: consume preserved notifications first, then socket frames.
- `_receive_from_socket()` for a pending request: consume only new socket frames while preserving unrelated notifications exactly once.

Regression-test that a pending preserved notification does not prevent the next request response from being received.

## Resource-bounded live smoke pattern

When validating a local live agent after an incident, execute the harness subprocess in a transient user scope, leaving the shared agent service untouched:

```bash
systemd-run --user --scope --collect --quiet \
  -p MemoryHigh=768M -p MemoryMax=1G -p MemorySwapMax=256M -p CPUQuota=200% \
  timeout --signal=TERM --kill-after=10s 90s \
  bash -lc 'cd <repo> && PYTHONPATH=scripts python3 scripts/gb-run.py ...'
```

The exact limits are workload-specific; the durable rule is a separate resource-bounded scope plus an outer TERM/KILL deadline. Capture the scope's memory peak and verify there are no residual runner processes or OOM records.

## Script scorer compatibility

Post-run scorer lookup should not assume every scenario ID is `<suite>.<name>`. Legacy scenario IDs may be unprefixed. Use the fast conventional lookup first, then fall back to searching suite JSON files by declared `id`; regression-test the fallback. A coding smoke fixture should include a real build/test manifest and tests in the layout expected by the language scorer, otherwise a successful agent turn can be recorded as an unscored or misleading failure.
