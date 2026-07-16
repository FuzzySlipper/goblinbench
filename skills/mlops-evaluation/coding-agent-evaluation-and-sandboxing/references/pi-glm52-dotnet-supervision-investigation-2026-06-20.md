# GLM52 / pi / GoblinBench .NET Supervision Investigation — 2026-06-20

## Context

GoblinBench maintainability probe:

- Scenario: `coding.maintainability-mini-service-python`
- Fixture: `fixtures/coding/maintainability-mini-service-python/`
- Candidate: `pi-coding-glm52-den-router`
- Path under suspicion:

```text
GoblinBench .NET CodingAgentRunner
  -> bwrap
  -> pi-coding-agent CLI --print --mode json --no-session
  -> den-router
  -> glm52
```

Patch reported that GLM52 worked normally in regular pi CLI/TUI through den-router, so the investigation shifted away from model/provider quality and toward GoblinBench harness behavior.

## Important findings

### 1. Source-side pi JSON update suppression was necessary but not sufficient

pi `--mode json` emits `message_update` events whose payloads contain cumulative partial assistant state. With reasoning-heavy models this can turn a normal run into hundreds of MB of stdout.

A local sandbox-runtime patch to pi print mode skipped these events when:

```text
PI_SUPPRESS_JSON_MESSAGE_UPDATES=1
```

This fixed the stdout/log blowup but did **not** by itself fix GLM52 failing inside the .NET runner.

### 2. Python/pytest runtime should be outside the fixture

Pre-provision pytest for Python coding fixtures under:

```text
.sandbox-runtime/python-fixture-venv/
```

and put it on sandbox `PATH`. Do **not** create `.venv` inside the fixture; GLM52 noticed fixture-local `.venv` during `find`, wasted context on environment internals, and polluted file discovery.

### 3. Controlled subprocess A/B matrix passed

A temporary investigation script was created:

```text
scripts/run-glm52-pi-harness-ab.py
```

It copied the fixture to disposable workspaces and varied:

- no-bwrap vs bwrap
- JSON vs text mode
- message-update suppression on/off where relevant
- smoke prompt vs actual maintainability prompt

Observed results from artifacts under:

```text
runs/pi-glm52-harness-ab/20260620-014924/
```

| Variant | Result |
|---|---|
| smoke, no bwrap, JSON suppress | pass, created `glm52_smoke.txt` |
| smoke, bwrap, JSON suppress | pass, created `glm52_smoke.txt` |
| maintainability, no bwrap, JSON suppress | pass, `10/10` pytest |
| maintainability, bwrap, JSON suppress | pass, `10/10` pytest |
| maintainability, no bwrap, text | pass, `10/10` pytest |
| maintainability, bwrap, text | pass, `10/10` pytest |

This showed that GLM52 + den-router + pi `--print` + pi `--mode json` + bwrap can all work together outside the .NET parent.

### 4. Exact failed `bwrap_argv` replay passed outside .NET

The strongest isolation test was to extract `bwrap_argv` from a failing `.NET CodingAgentRunner` run and execute the exact argv from a Python parent.

Failing .NET run:

```text
run-20260620-090457-4b1c7b72
```

Replay artifact:

```text
runs/pi-glm52-harness-ab/exact-dotnet-argv-run-20260620-090457-4b1c7b72/
```

Replay result:

```text
exit_code: 0
agent_end: true
edits: 3
stdout: ~346 KB
```

This ruled out the exact bwrap argv, fixture, den-router model, and pi CLI arguments as sufficient causes.

### 5. Actual .NET runner remained failing

Representative failing .NET runs after cleanup:

```text
run-20260620-090230-d8b612d8
run-20260620-090457-4b1c7b72
run-20260620-091047-6f4273b4
```

Common symptoms:

- child exits `137`
- no stderr
- no source edits
- small stdout after `message_update` suppression
- failure happens after inspection/read turns, before first edit
- scenario timeout is much larger than observed duration, so GoblinBench is not intentionally timing out the run

An experiment changing `CodingAgentRunner` stdout capture from filtered line reads to raw chunk draining did **not** fix the failure and was reverted.

## Current classification

Classify these GLM52 maintainability failures as:

```text
runner/substrate failure in .NET CodingAgentRunner supervision path
```

Do **not** classify them as:

- GLM52 model-quality failure
- den-router general failure
- bwrap general failure
- pi `--print` / `--mode json` general failure
- simple disk/memory-full issue

## Reusable debugging pattern

When a coding-agent subprocess fails under GoblinBench but works manually:

1. Build a tiny external reproducer that launches the same agent/fixture with capped stdout.
2. Test no-bwrap vs bwrap and text vs JSON outside the .NET runner.
3. Extract `bwrap_argv` from `run.json` / artifacts and replay the exact argv from a different parent process.
4. If exact argv passes outside .NET but fails inside .NET, focus on `CodingAgentRunner` parent/supervision/capture/lifecycle rather than model, provider, bwrap, or pi CLI arguments.

## Design implication

If this class of issue recurs, consider adding a Python or standalone supervisor shim:

```text
.NET Runner -> small subprocess supervisor -> bwrap -> pi
```

The .NET runner would remain the orchestrator/scorer writer, but the fragile child process lifecycle would be managed by a parent implementation already proven to execute the exact argv successfully.

Alternative substrate: a future `PiCrewWorkerRunner` could use controller/pi-crew workers for realistic agent behavior, but it needs a separate isolation/artifact design; bwrap is easy around one-shot CLI processes and much less natural around long-lived workers.
