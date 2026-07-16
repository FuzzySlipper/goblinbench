# Python runner validation for GLM52 coding-agent path — 2026-06-20

## Context

GoblinBench's .NET `CodingAgentRunner` repeatedly failed the GLM52 den-router coding-agent candidate on `coding.maintainability-mini-service-python` with child exit `137` before edits, even after fixing stdout `message_update` amplification and pytest runtime setup.

A background agent produced a drop-in Python runner (`scripts/gb-run.py`) that writes the same `runs/<run-id>/` artifact contract consumed by `gb-score.py` and `gb-results.py`.

## Validation command

```bash
python3 scripts/gb-run.py \
  --suite coding \
  --scenario coding.maintainability-mini-service-python \
  --candidate pi-coding-glm52-den-router
```

## Result

Successful run:

```text
runs/run-20260620-155857-0cd7b4a4
status: OK
candidate duration: 207024ms
exit_code: 0
timed_out: false
files_changed: service/handlers/customers.py
stdout: ~389 KB
stderr: 0
```

Scores:

| scorer | pass | score | summary |
|---|---:|---:|---|
| coding-tests | yes | 1.0 | pytest: 10/10 passed |
| structure-metrics | yes | 1.0 | 8 impl files, 21 functions, mean 7.4 LOC/fn |
| maintainability-metrics | yes | 1.0 | changed 1 file, central-change-share 100%, largest-fn Δ +20, handler max 37 LOC |
| latency | info | 0.0 | 207024ms |

`gb-results.py import --quiet` indexed the Python-produced run successfully; `gb-results.py cell run-20260620-155857-0cd7b4a4 coding.maintainability-mini-service-python pi-coding-glm52-den-router --format json` returned the expected cell.

## Important porting gotcha

Initial Python-runner attempt launched bwrap but appeared to sit in the two-bwrap-process pre-exec state for several minutes before `node/pi` appeared. The successful run required removing `start_new_session=True` from the bwrap `subprocess.Popen(...)` call in `scripts/gb/runners/coding_agent.py`, matching the earlier known-good Python A/B reproducer.

Keep this as a Python-runner porting pitfall:

```python
subprocess.Popen(..., text=True)  # no start_new_session=True for this bwrap/pi path
```

If a future Python-runner coding-agent run appears hung before `node/pi` starts, inspect the process tree. If only two `bwrap` processes exist and no `node` child, compare the launch flags against the known-good path before blaming the model/provider.

## Model/style signal from the validated run

GLM52 is usable for this probe once run through the Python execution layer:

- Correctness: passes 10/10.
- Style: centralizes the feature in `service/handlers/customers.py`.
- It adds helper functions inside the handler file rather than using existing seams or creating a helper module.
- Handler max function was 37 LOC — less bloated than the earlier DeepSeek Flash baseline, but still god-handler-ish by changed-file concentration.

## Workflow lesson

When isolating coding-agent substrate failures:

1. Test normal model/router behavior separately.
2. Test exact bwrap argv outside the parent runner.
3. If exact argv succeeds outside the parent but fails under one runtime, treat parent supervision as suspect.
4. Validate an alternate runner by checking both primary score and downstream `gb-results.py` import/cell compatibility.
