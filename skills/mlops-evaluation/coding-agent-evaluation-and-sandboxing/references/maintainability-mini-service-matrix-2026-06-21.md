# Maintainability Mini-Service Matrix — 2026-06-21

GoblinBench session reference for the first full 6-model × 4-language maintainability-pressure matrix.

## Scope

Scenarios:
- `coding.maintainability-mini-service-python`
- `coding.maintainability-mini-service-typescript`
- `coding.maintainability-mini-service-go`
- `coding.maintainability-mini-service-rust`

Candidates:
- `pi-coding-deepseek-pro-den-router`
- `pi-coding-glm52-den-router`
- `pi-coding-stepfun-den-router`
- `pi-coding-minimax-den-router`
- `pi-coding-qwen-max-den-router`
- `pi-coding-kimi-code-den-router`

Run IDs:
- Python: `run-20260621-063745-1472b013`
- TypeScript: `run-20260621-065203-e3c167a1`
- Go: `run-20260621-070708-76fcf81c`
- Rust: `run-20260621-072309-206546fd`

Artifacts:
- Flat summary: `/home/dev/goblinbench/runs/maintainability-matrix-logs/maintainability-matrix-summary.md`
- Driver summary JSON: `/home/dev/goblinbench/runs/maintainability-matrix-logs/matrix-summary-20260621-133745.json`
- Den doc: `goblinbench/maintainability-mini-service-matrix-6-models-4-languages`

## Execution pattern

Use one language-at-a-time batches for pi coding-agent den-router matrix runs. Candidate configs share sandbox/workspace plumbing, so do not launch all language/model cells concurrently unless the runner has been changed to provide per-cell isolated workspaces. Sequential language batches make provider/harness failures easier to attribute.

Useful shape:

```bash
python3 scripts/gb-run.py \
  --suite coding \
  --scenario coding.maintainability-mini-service-go \
  --candidate pi-coding-deepseek-pro-den-router,pi-coding-glm52-den-router,pi-coding-stepfun-den-router,pi-coding-minimax-den-router,pi-coding-qwen-max-den-router,pi-coding-kimi-code-den-router
```

Import each completed run:

```bash
python3 scripts/gb-store.py import --run-json runs/<run-id>/run.json
```

## Candidate/router gotchas

- Router exposed `qwen-max`, not stale `qwenmax`. Add/use exact-router-ID coding candidate `pi-coding-qwen-max-den-router`.
- Router exposed `kimi-code`; add/use exact-router-ID coding candidate `pi-coding-kimi-code-den-router`.
- Direct `/v1/chat/completions` smoke can return HTTP 200 with empty content for reasoning-ish models; this only proves routability, not coding-agent compatibility.

## Harness/scorer lessons

- `scripts/scorers/structure-metrics.py` must honor scenario `structure-metrics.scan_dir`; otherwise Rust/TS integration tests can contaminate impl-file counts. A regression test should assert this behavior.
- Treat runner status, behavior tests, and maintainability metrics separately. A timed-out candidate may still leave a patch; manually salvage-score it before calling it only a substrate failure.
- For timed-out Rust/Minimax in this run, salvage scoring also failed compile (`Option<String>` where `Option<&str>` expected), so classify as timeout + incomplete implementation.

## Result summary

23/24 cells passed behavior tests.

| Model | Pass cells | Timeouts | Avg sec completed | Avg central share | Notable split cells |
|---|---:|---:|---:|---:|---|
| DeepSeek Pro | 4/4 | 0 | 76.8 | 100% | — |
| GLM52 | 4/4 | 0 | 309.2 | 69% | TypeScript, Go |
| StepFun | 4/4 | 0 | 166.2 | 100% | — |
| Minimax | 3/4 | 1 | 176.9 | 77% | Go |
| Qwen Max | 4/4 | 0 | 110.7 | 100% | — |
| Kimi Code | 4/4 | 0 | 139.3 | 100% | — |

Style signal:
- Python: every model solved it and centralized in `service/handlers/customers.py`.
- TypeScript: GLM52 uniquely split into `src/bulk-import.ts`, handler, and validation; others stayed handler-only.
- Go: GLM52 and Minimax split into `bulk_import.go` + `customers.go`; others stayed handler-only.
- Rust: passing cells were effectively `src/customers.rs`-centric.

## Reporting preference

For Patch, present this class of result as a flat scannable table first. Separate harness/provider/runtime failures from behavior-test failures and style/maintainability signal.