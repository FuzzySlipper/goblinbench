# Batch Ingestion Language-Gravity Trial (2026-06-19)

Session-specific reference for GoblinBench task #2749: extending the interface-seeded Batch Ingestion style probe from Python to TypeScript and running the first same-model comparison.

## Probe shape

Same logical task in each language:

```text
validate → transform → filter → aggregate
```

Keep the interfaces fixed and only let the agent fill implementation bodies.

- Python fixture: `fixtures/coding/batch-ingestion/`
- TypeScript fixture: `fixtures/coding/batch-ingestion-ts/`
- Python scenario: `suites/coding/batch-ingestion-python.json`
- TypeScript scenario: `suites/coding/batch-ingestion-typescript.json`

## TypeScript port pattern

Recommended TS fixture shape:

```text
fixtures/coding/batch-ingestion-ts/
  package.json              # `npm test` -> `vitest run`
  tsconfig.json             # strict TS
  src/
    types.ts                # fixed interface; do not score as impl
    validate.ts             # stubs
    transform.ts            # stubs
    filter.ts               # stubs + FilterRule interface
    aggregate.ts            # stubs
  tests/
    validate.test.ts
    transform.test.ts
    filter.test.ts
    aggregate.test.ts
```

Use Vitest and a lockfile so scorer installs are reproducible. Tests should constrain correctness and mutation/order behavior, not style.

## Scoring/metrics changes that mattered

- `scripts/scorers/coding-tests.py` already auto-detects `package.json` as TypeScript and runs `npm install --ignore-scripts` then `npm test -- --no-coverage`.
- After npm scoring, delete generated `node_modules`, `coverage`, and `dist`; these are dependency/build artifacts, not benchmark artifacts.
- `CodingAgentRunner` should also ignore `node_modules`, `coverage`, and `dist` in patch/file-change capture.
- `scripts/structure-metrics.py` was extended from Python AST-only to lightweight TS/JS text parsing:
  - count `export function`, ordinary functions, and const arrow functions;
  - approximate typed params and return annotations;
  - exclude `types.ts`, test files, and generated dirs;
  - preserve the same metric names as Python so reports can table languages together.

## Verification pattern

1. Run stub scenario via deterministic/scripted candidate. Expected: tests fail, metrics still emit.
2. Create a temp reference implementation outside the committed fixture. Expected: all tests pass via `scripts/scorers/coding-tests.py`.
3. Run one real coding-agent candidate per language.
4. Recompute structure metrics after any scorer changes when comparing earlier runs.

## First same-model result

Candidate: `pi-coding-deepseek-flash-den-router`.

| Language | Run | Duration | Tests | Impl LOC | Functions | Mean LOC/fn | p95 LOC/fn | Docs/comments | Type depth |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Python | `run-20260619-114108-07145f49` | 126.1s | 49/49 | 329 | 13 | 19.2 | 43 | 100% | 100% |
| TypeScript | `run-20260619-122416-7884702b` | 88.7s | 51/51 | 368 | 20 | 14.2 | 37 | 15% | 100% |

Early observed style signal: TypeScript solution decomposed into more helpers (`20` functions vs Python `13`) with slightly more LOC but lower mean LOC/function and much lower doc/comment coverage. Both were correct, so this is useful bounded “training-data gravity” signal rather than correctness noise.

## Pitfalls

- Do not let fixed interface files (`types.py`, `types.ts`) contribute to style metrics.
- Do not let generated caches/dependencies (`__pycache__`, `.pytest_cache`, `node_modules`, `coverage`, `dist`) pollute patch artifacts or style metrics.
- `npm test` directly can fail with `vitest: command not found` if deps are not installed; use the scorer path or run `npm install --ignore-scripts` first. Capture the install+test flow as the durable pattern, not the transient missing-binary failure.
- The TS text parser is intentionally lightweight. Treat TS metrics as approximate but stable enough for cross-run comparison; upgrade to TypeScript compiler API or ts-morph only if the lightweight parser starts missing common generated shapes.
