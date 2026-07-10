# Codex app-server coding-agent runner

## Purpose

`codex-app-server` is an **environment-realized** CodingAgent runner. It drives the local Codex app-server instead of emulating an agent with one-shot Chat Completions.

## Service and protocol evidence

- Socket: `/run/user/1001/codex-app-server/app-server.sock`
- Transport: RFC 6455 WebSocket frames over that Unix socket
- Protocol lifecycle: `initialize` → `initialized` notification → `thread/start` → `turn/start` → streamed events → `turn/completed`
- Server evidence from the smoke artifact: `cliVersion` `0.144.1`, resolved model `gpt-5.6-terra`, provider `openai`.

## Isolation and artifacts

For each candidate/scenario run, the runner copies the declared fixture into the candidate artifact tree and makes that host path the Codex thread CWD and sole declared writable root. It records:

- copied fixture path and final workspace diff;
- requested model, effort, thread ID, turn ID, status, duration, and timeout state;
- bounded raw protocol evidence in `artifacts/codex-events.jsonl`;
- bounded agent text in `artifacts/codex-response.txt`;
- `artifacts/agent.patch`.

The app-server is not restarted or reconfigured by benchmark runs.

## Resource-safety contract

A previous live smoke exposed a dangerous protocol condition: `remoteControl/status/changed` notifications could arrive while a request response was pending. Reading from the normal buffered receive path requeued that same notification, replaying it indefinitely while the in-memory event list grew.

The runner now:

1. streams event evidence to JSONL with a 2 MiB artifact budget;
2. caps buffered notifications at 512 events / 2 MiB;
3. caps any individual WebSocket frame at 4 MiB;
4. caps retained agent text at 32,768 characters;
5. reads pending RPC responses directly from the socket rather than draining/requeueing preserved notifications;
6. limits `thread/start` and `turn/start` acknowledgements independently (default 30 s; smoke configuration uses 15 s).

Exceeding these limits is a classified runner/substrate failure with its partial event artifact retained. Real-service smoke commands should additionally be run in a transient systemd scope with explicit memory limits, not in the gateway cgroup.

## Verified live smoke

Command:

```bash
systemd-run --user --scope --collect --quiet \
  -p MemoryHigh=768M -p MemoryMax=1G -p MemorySwapMax=256M -p CPUQuota=200% \
  timeout --signal=TERM --kill-after=10s 60s \
  bash -lc 'cd /home/dev/goblinbench && PYTHONPATH=scripts python3 scripts/gb-run.py \
    --suite coding-smoke --candidates candidates.codex-app-server-smoke.json'
```

Result: `run-20260710-164602-88d4b13d` completed successfully in 50,921 ms. It created only `src/main.py` in the copied `e2e-pi-mock` fixture, with `turn_status=completed`. The protocol artifact was 124 KiB; the Codex service memory peak was 85.7 MiB. No OOM event occurred.

## Current limitations

- The raw server event schema is preserved but not yet normalized into a stable cross-agent provenance envelope; that is task #5544.
- A real turn can still fail for service/model reasons; the runner deliberately reports that separately from the fixture diff and test outcome.
- The smoke fixture currently verifies filesystem mutation and standard runner artifacts. Broader coding-scorer coverage belongs in subsequent coding-scenario work.
