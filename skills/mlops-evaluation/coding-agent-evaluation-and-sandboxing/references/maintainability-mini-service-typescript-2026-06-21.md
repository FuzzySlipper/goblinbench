# Maintainability Mini-Service TypeScript Probe — 2026-06-21

Session-specific GoblinBench note for the class-level `coding-agent-evaluation-and-sandboxing` skill.

## What was added

Added a TypeScript sibling to the Python maintainability-pressure probe:

- Scenario: `suites/coding/maintainability-mini-service-typescript.json`
- Fixture: `fixtures/coding/maintainability-mini-service-ts/`
- Source seams: `src/router.ts`, `src/container.ts`, `src/auth.ts`, `src/validation.ts`, `src/repository.ts`, `src/audit.ts`, `src/models.ts`, `src/handlers/customers.ts`
- Tests: `tests/existing-customers.test.ts`, `tests/bulk-import.test.ts`
- Baseline snapshot: `.goblinbench/maintainability-baseline.json`

The fixture intentionally starts red: existing route tests pass, bulk-import behavior fails on the `501` stub.

## Scorer update pattern

`maintainability-metrics.py` was generalized from Python-only AST metrics to also support lightweight TypeScript/JS text metrics. For TS scenarios, set scorer params explicitly:

```json
"maintainability-metrics": {
  "source_root": "src",
  "baseline_path": ".goblinbench/maintainability-baseline.json",
  "central_paths": ["src/router.ts", "src/container.ts", "src/handlers/customers.ts"],
  "setup_paths": ["src/container.ts"],
  "handler_paths": ["src/handlers/customers.ts"]
}
```

Regression tests were added to ensure the TS fixture is detected, the scenario points at an existing fixture, and TS maintainability metrics see 8 source files and a zero-delta baseline.

## Verification commands/results

```bash
python3 -m pytest tests/ -q
# 9 passed

python3 -m compileall -q scripts tests
# passed

python3 scripts/gb-run.py --suite coding \
  --scenario coding.maintainability-mini-service-typescript \
  --candidate coding-scripted
# substrate OK; coding-tests 3/10; structure-metrics OK; maintainability-metrics OK
```

The red scripted baseline is useful: it verifies the scorer substrate without pretending the stub implementation is correct.

## DeepSeek Flash first model trial

Command:

```bash
python3 scripts/gb-run.py --suite coding \
  --scenario coding.maintainability-mini-service-typescript \
  --candidate pi-coding-deepseek-flash-den-router
```

Run: `run-20260621-051347-cec759dd`

Result:

- Candidate substrate: OK, ~49.9s
- `coding-tests`: PASS, `10/10` Vitest tests
- `structure-metrics`: OK — 8 impl files, 9 functions, mean 14.7 LOC/fn, type-depth 100%, docstring 0%, test:source 0.58
- `maintainability-metrics`: OK — changed 1 file, max-change-share 100%, central-change-share 100%, largest-fn Δ +43, handler max 64 LOC

Style read: behaviorally correct, architecturally centralized. DeepSeek Flash reused some existing seams (`canBulkImportCustomers`, validation, repository, audit), but placed the whole bulk workflow in `src/handlers/customers.ts`. This mirrors the Python baseline pattern: tests pass, but maintainability-pressure metrics show fat-handler / central changed mass.

## Reusable lesson

For maintainability-pressure probes, always report correctness and architecture signal separately:

- Correctness: did `coding-tests` pass?
- Style pressure: which files changed, central changed-mass share, largest function delta, handler max LOC.

A model can pass all behavior tests while still producing the exact architectural gravity the probe is designed to measure.
