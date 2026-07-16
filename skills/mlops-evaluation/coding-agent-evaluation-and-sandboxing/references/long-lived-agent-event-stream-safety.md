# Long-Lived Agent Event-Stream Safety

## Trigger

Use this when a coding-agent runner talks to an app server, WebSocket, SSE stream, MCP session, or other long-lived protocol and retains tool/turn events as benchmark artifacts.

## Failure pattern

A real coding smoke on 2026-07-10 exhausted host RAM and swap. The kernel killed a `python3` terminal child at roughly 16.6 GiB anonymous RSS. The child belonged to the Hermes gateway cgroup, which made the incident look like gateway growth, but the allocation came from the live benchmark runner.

The dangerous shape was:

- append every raw server message to an in-memory event list;
- queue notifications received while awaiting a JSON-RPC response;
- collect all assistant deltas in memory;
- wait for an acknowledgement/completion that may never arrive.

A streaming server can then cause double retention (event log + pending-notification queue) until timeout or OOM.

## Required runner contract

1. Write raw events incrementally to `events.jsonl`; do not retain the complete stream in Python memory.
2. Keep a bounded in-memory summary/ring buffer for diagnostics only. Bound both event count and aggregate bytes.
3. Bound pending notifications, assistant text, per-event payload size, and retained tool output independently. Write truncation counters/bytes to the result artifact.
4. Use separate deadlines for protocol acknowledgement (for example `turn/start` response) and terminal turn completion. Do not buffer an unbounded notification stream while awaiting an acknowledgement.
5. On a limit or deadline breach: issue one best-effort interrupt/cancel, close transport, snapshot the workspace, and return a distinct `runner_substrate_failure`/`event_stream_limit` result with partial artifacts.
6. Run live agent benchmark subprocesses under a separately limited systemd scope/cgroup where practical; do not allow one pathological turn to consume the interactive gateway's entire memory and swap.

## Diagnosis checklist

- Read the kernel OOM event for killed PID, anonymous RSS, cgroup, and free swap.
- Correlate the PID with the actual tool/subprocess command; a child is charged to its service cgroup.
- Inspect raw event, notification, response-text, retry, and tool-output buffers for unbounded growth.
- Inspect protocol logs for missing response/completion events or repeated notifications.
- Treat retry loops that log full tracebacks as amplifiers (CPU/journal pressure), but distinguish them from the process doing the actual allocation.

## Artifact fields

Record: `event_count_seen`, `event_bytes_seen`, `event_bytes_written`, `events_truncated`, `notification_queue_peak`, `assistant_bytes_retained`, acknowledgement deadline, turn deadline, interrupt outcome, and termination reason.
