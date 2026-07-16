# GoblinBench Python-only runner cleanup — 2026-06-21

## Durable lesson

When a benchmark harness has a verified replacement execution path, keeping the old runner implementation in-tree can mislead agents into using or preserving the wrong path. For GoblinBench, after `scripts/gb-run.py` covered the live candidates/scorers and fixed the GLM52/.NET supervision failure class, the right cleanup was to remove the legacy .NET runner/tests rather than document them as a fallback.

## Cleanup pattern

1. Verify the replacement runner first:
   - deterministic smoke: `python3 scripts/gb-run.py --suite orchestrator --candidate scripted-deterministic`
   - store/report smoke: `scripts/gb-store.py status`, `scripts/gb-report.py ...`
   - Python tests and compile check: `python3 -m pytest tests/ -q`, `python3 -m compileall -q scripts tests`
2. Delete legacy implementation and tests once the replacement is canonical.
3. Patch root detection and docs that assumed the deleted tree exists.
4. Remove old scenarios/fixtures that only exist to exercise the removed substrate, unless they are intentional benchmark subject matter.
5. Scan for stale guidance:
   - `git grep -n -E 'dotnet run|dotnet test|src/GoblinBench|GoblinBench\.Runner|DOTNET|NUGET|run_dotnet' -- ':!fixtures/codebase-analysis/**' ':!*.pyc'`
   - `git ls-files '*.cs' '*.csproj' '*.slnx' | grep -v '^fixtures/codebase-analysis/'`
6. Keep benchmark-subject C# fixtures if they are data for a codebase-analysis scenario; those are not runner legacy.
7. Clean generated artifacts from git tracking (`__pycache__`, `.pyc`) and add ignores.
8. Leave the committed SQLite store unchanged after smoke tests: delete the smoke run with `gb-store delete --run-id <id> --files`, then restore `runs/goblinbench.sqlite` if the smoke was only validation.

## Tests added in the session

`tests/test_store_reporting.py` covered:
- repo-root detection without `src/`
- `ingest_run` idempotence
- inline click-through artifacts
- ring-buffer pruning leaving DB history intact
- `gb-store delete` safety rules
- report generation and empty-filter failure behavior
- `.csproj` no longer being detected as a supported coding fixture language

## Pitfalls caught

- Store repo-root detection still depended on `src/`; deleting `src/` would have broken CLIs without a test.
- Docs and scenario prompts can contain hidden old-runner commands even after README is updated.
- Tracked `__pycache__` files make cleanup noisy and should be untracked, not merely deleted locally.
- Do not treat all C# in the repo as legacy: codebase-analysis fixtures may intentionally contain C# subject code.
