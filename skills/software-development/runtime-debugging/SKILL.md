---
name: runtime-debugging
description: Use when stepping through live Python or Node.js programs with pdb, debugpy, node inspect, Chrome DevTools Protocol, or PTY debugger workflows.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, python, nodejs, debugpy, pdb, inspector, dap, cdp]
    related_skills: [systematic-debugging]
---

# Runtime Debugging

## Overview

Use this umbrella when logs and tests are not enough and you need to step through a live program, inspect frames, pause on breakpoints, or attach to a running process. Start with a reproduction and a hypothesis; choose the narrowest debugger that can answer the question.

## When to Use

- A collection mutates unexpectedly and you need to watch the exact frame.
- A long-lived server/worker only fails at runtime.
- A UI/TUI process needs Node inspector or CDP-level inspection.
- A pytest/vitest test needs breakpoint-driven diagnosis.

Do not use a debugger for issues obvious from a stack trace, `--showlocals`, or one minute of targeted logging.

## Choosing a Debugger

| Runtime | Local/simple | Remote/headless | Scriptable protocol |
| --- | --- | --- | --- |
| Python | `pdb`, `breakpoint()`, `pytest --pdb` | `remote-pdb`, `debugpy --listen` | DAP via `debugpy` |
| Node.js/TS | `node inspect`, `debugger;` | `node --inspect[-brk] host:port` | Chrome DevTools Protocol |

## Python Recipes

### pdb and pytest

- Drop into pdb on failure: `python -m pytest tests/foo_test.py::test_bar --pdb -p no:xdist`.
- Break at start: insert `breakpoint()` or use `pytest --trace`.
- Show locals without a debugger: `python -m pytest -vv --tb=long --showlocals`.
- Avoid xdist while debugging; pdb under xdist often appears to hang.

### debugpy

Install and verify:

```bash
pip install debugpy
python -c "import debugpy; print(debugpy.__version__)"
```

Launch under debugpy:

```bash
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client your_script.py arg1
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client -m your.module
```

Source-edit attach point:

```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
debugpy.wait_for_client()
debugpy.breakpoint()
```

Attach-to-PID requires ptrace permissions and a compatible environment; if it fails on hardened kernels, launch under debugpy instead.

## Node.js Recipes

### Inspector flags

```bash
node --inspect script.js
node --inspect-brk script.js
node --inspect=127.0.0.1:9230 script.js
node --inspect-brk --import tsx script.ts
node --inspect-brk -r tsx/cjs script.ts
```

### Attach to a running process

1. Send `SIGUSR1` to enable inspector on an existing Node process.
2. Read the printed `ws://127.0.0.1:9229/<uuid>` debugger URL.
3. Attach via `node inspect`, Chrome DevTools, or a small CDP client.

### Tests and TUIs

- Vitest single test: `node --inspect-brk ./node_modules/vitest/vitest.mjs run --no-file-parallelism path/to/test.ts`.
- Agent terminals need PTY for debugger REPLs; use `terminal(pty=true)` or background process + `process(action='submit', ...)`.

## Hermes-Specific Debugging Notes

- Python gateway/agent code uses Python debuggers; Ink/TUI and tsx-run UI tests use Node inspector.
- Test wrappers may scrub `HOME` or credentials. Reproduce with raw pytest/node first if user config matters, then confirm under wrappers.
- Long-lived daemons should be started under debugger control rather than attached after the fact when ptrace or port exposure is unreliable.

## Common Pitfalls

1. **No PTY for REPL debuggers.** `pdb`, `node inspect`, and similar REPLs need an interactive terminal path.
2. **Forgetting `wait_for_client`.** `debugpy.listen()` alone does not pause execution.
3. **Port conflicts.** Inspector/debugpy ports are often already bound; choose a free localhost port.
4. **Debugging the wrong runtime.** Python worker bugs need Python tools; Node UI/TUI bugs need Node inspector.
5. **Leaving breakpoints behind.** Search for `breakpoint()`, `set_trace()`, `debugpy.listen`, and `debugger;` before finalizing.

## Verification Checklist

- [ ] Reproduction command is known and scoped.
- [ ] Debugger selected matches runtime and environment.
- [ ] PTY/background process handling is appropriate.
- [ ] Findings are confirmed by rerunning the repro/test without debugger-only changes.
- [ ] Temporary breakpoints/listeners are removed.
