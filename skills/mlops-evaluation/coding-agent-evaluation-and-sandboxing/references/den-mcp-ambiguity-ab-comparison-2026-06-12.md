# Den MCP ambiguity A/B comparison — requested router models (2026-06-12)

Fresh run requested by Patch against local den-router models: `glm`, `kimi`, `mimo`, `nemotron`, `stepfun`, `hy3`, `minimax`.

## Commands / shape

From `/home/dev/goblinbench`:

```bash
python3 scripts/generate-den-mcp-ambiguity-suite.py --variant baseline
python3 scripts/generate-den-mcp-ambiguity-suite.py --variant hinted

# Full runs used dotnet runner per model/variant:
dotnet run --no-restore --project src/GoblinBench.Runner -- \
  --suite den-mcp-ambiguity \
  --candidate den-router-<model>-tool-behavior

dotnet run --no-restore --project src/GoblinBench.Runner -- \
  --suite den-mcp-ambiguity-hinted \
  --candidate den-router-<model>-tool-behavior
```

Smoke probe before scheduling found:

- `nemotron`: 404, `The model 'nemotron' does not exist.` — skipped full run.
- `hy3`: 404, `The model 'hy3' does not exist.` — skipped full run.
- `glm`, `kimi`, `mimo`, `stepfun`, `minimax`: routable and full runs completed.

Artifacts:

- Local merged summary: `/home/dev/goblinbench/runs/den-mcp-ambiguity-requested-20260612-054430/merged-ab-summary.md`
- JSON: `/home/dev/goblinbench/runs/den-mcp-ambiguity-requested-20260612-054430/merged-ab-summary.json`
- Den doc: `goblinbench/den-mcp-ambiguity-ab-requested-2026-06-12`

## Summary

| model | baseline pass | hinted pass | Δ | avg latency baseline | avg latency hinted |
|---|---:|---:|---:|---:|---:|
| glm | 3/6 | 5/6 | +2 | 23.1s | 16.8s |
| minimax | 2/6 | 5/6 | +3 | 19.3s | 17.2s |
| stepfun | 3/6 | 4/6 | +1 | 8.9s | 7.5s |
| kimi | 2/6 | 3/6 | +1 | 20.3s | 13.1s |
| mimo | 1/6 | 1/6 | +0 | 7.1s | 7.2s |

## Scenario matrix (baseline/hinted)

| scenario | glm | minimax | stepfun | kimi | mimo |
|---|---|---|---|---|---|
| clarify-destructive-doc-action | ✗/✓ | ✗/✓ | ✗/✗ | ✗/✓ | ✗/✗ |
| comment-vs-update-document | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✓ | ✓/✗ |
| den-mcp-doc-system-planner | ✗/✗ | ✗/✗ | ✗/✗ | ✗/✗ | ✗/✗ |
| persona-not-project-task-message | ✓/✓ | ✓/✓ | ✓/✓ | ✗/✗ | ✗/✗ |
| project-explicit-report-doc | ✗/✓ | ✗/✓ | ✗/✓ | ✓/✓ | ✗/✓ |
| search-vs-get-document | ✓/✓ | ✗/✓ | ✓/✓ | ✗/✗ | ✗/✗ |

## Takeaways

- Hints had the largest gain for `minimax` (+3) and `glm` (+2).
- `glm` and `minimax` reached 5/6 hinted, the best of this requested set.
- `den-mcp-doc-system-planner` stayed unsolved across all tested models and variants.
- `stepfun` remains fast and solid (4/6 hinted), but still fails `clarify-destructive-doc-action` even with hints.
- `mimo` remained weak (1/6) and regressed on `comment-vs-update-document` with hints.
