# Codex app-server coding-agent runner

## Purpose

`codex-app-server` is an **environment-realized** CodingAgent runner. It drives the local Codex app-server instead of emulating an agent with one-shot Chat Completions.

## Service and protocol evidence

- Socket: `/run/user/1001/codex-app-server/app-server.sock`
- Transport: RFC 6455 WebSocket frames over that Unix socket
- Protocol lifecycle: `initialize` → `initialized` notification → `thread/start` → `turn/start` → streamed events → `turn/completed`
- Server evidence from the smoke artifact: `cliVersion` `0.144.1`, resolved model `gpt-5.6-terra`, provider `openai`.

## Isolation and artifacts

For each candidate/scenario run, the runner copies the declared fixture into the candidate artifact tree. The absolute copied-fixture path is sent as both `cwd` and `runtimeWorkspaceRoots` on `thread/start` **and** `turn/start`; under the default `workspace-write` sandbox it is also the sole declared writable root. The runner prepends a symmetric execution-isolation contract requiring the first command to be standalone `pwd`. A cell fails unless the completed command output exactly matches the copied fixture and every command CWD exposed by the protocol remains under it. It records:

- copied fixture path and final workspace diff;
- requested and app-server-resolved model/effort, thread ID, turn ID, status,
  duration, and timeout state;
- bounded raw protocol evidence in `artifacts/codex-events.jsonl`;
- bounded agent text in `artifacts/codex-response.txt`;
- `artifacts/agent.patch`;
- the stable `artifacts/environment.json` envelope, including exact resolved
  model/provider, app-server version, token usage, workspace hash, and activity
  counts exposed by the protocol.

Requested reasoning effort is supplied in the thread configuration as well as
the turn override. The runner requires `thread/start.reasoningEffort` to equal
the request before benchmark work begins, preventing a default-effort thread
from being mislabeled as the comparison effort.

The app-server is not restarted or reconfigured by benchmark runs.

The direct runner defaults to `workspace-write`. Direct-versus-Crew candidate
matrices explicitly select `danger-full-access`, matching Rusty Crew's current
external-turn sandbox policy; the locality preflight remains mandatory and is
the comparison harness's fail-closed guard against a wrong working directory.

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

Result: `run-20260710-165700-a2959c57` completed successfully in 25,186 ms. It created only `src/main.py` in the copied `e2e-pi-mock` fixture, with `turn_status=completed`; the copied fixture's `coding-tests` scorer ran pytest and passed **2/2** tests (score 1.0). No OOM event occurred.

## Current limitations

- A real turn can still fail for service/model reasons; the runner deliberately reports that separately from the fixture diff and test outcome.
- The smoke fixture currently verifies filesystem mutation and standard runner artifacts. Broader coding-scorer coverage belongs in subsequent coding-scenario work.

For a direct-versus-Rusty-Crew run using the same requested Codex model, see
[`rusty-crew-runner.md`](rusty-crew-runner.md). The raw server events remain
available for diagnosis while the environment envelope is the stable reporting
surface.
