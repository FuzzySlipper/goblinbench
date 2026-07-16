# Python Scoring Pipeline — Full Architecture

Introduced June 2026, GoblinBench. Hybrid .NET + Python scoring system.

## File locations

| Path | Purpose |
|---|---|
| `scripts/gb-score.py` | Pipeline orchestrator — reads run.json, dispatches, writes back |
| `scripts/scorers/coding-tests.py` | Language-detecting test runner |
| `scripts/scorers/structure-metrics.py` | AST analysis wrapper |
| `scripts/structure-metrics.py` | Standalone AST analyzer (used by the wrapper) |

## Integration point

In `src/GoblinBench.Runner/Program.cs`, after `run.json` is written:

```csharp
var pythonPipeline = Path.Combine(repoRoot, "scripts", "gb-score.py");
if (File.Exists(pythonPipeline))
{
    // Create Process with python3, pass runDir, capture output
    // On success: re-read run.json to get updated scores
}
```

## Scorer script contract

Each script in `scripts/scorers/<id>.py` accepts:
- `--fixture-dir <path>` (required)
- `--artifact-dir <path>` (optional)
- `--threshold <float>` (optional)
- `--params <json>` (optional — scenario-specific config)

Emits one JSON to stdout:

```json
{
  "scorer_id": "coding-tests",
  "scorer_name": "Coding Test Scorer",
  "scoring_kind": "script",
  "success": true,
  "score": 1.0,
  "passed": true,
  "human_summary": "PASS",
  "explanation": "pytest: 49/49 passed",
  "detail": { "language": "python", "passed": 49, "total": 49 }
}
```

## Language detection (coding-tests.py)

```
pyproject.toml or pytest.ini → pytest
*.csproj                     → dotnet restore/build/test
Cargo.toml                   → cargo test
package.json                 → npm test (auto-installs deps)
```

Detection is priority-ordered: Python > dotnet > Rust > TypeScript. First match wins.

## Score replacement logic

The Python pipeline replaces .NET scores when a Python script exists for the same scorer_id. Logic in `gb-score.py`:

```python
existing = [s for s in candidate_result["scores"]
            if s.get("scorer_id") == scorer_id]
if existing and existing[0].get("scoring_kind") != "script":
    # Remove .NET score, Python will replace it
    candidate_result["scores"] = [
        s for s in candidate_result["scores"]
        if s.get("scorer_id") != scorer_id
    ]
elif existing:
    continue  # already scored by Python, skip
```

## Structure metrics contract

`detail` dict emitted by `structure-metrics.py`:

```json
{
  "total_impl_files": 5,
  "total_test_files": 4,
  "total_impl_lines": 256,
  "total_test_lines": 555,
  "loc_per_file": [39, 71, 57, 46, 43],
  "total_functions": 13,
  "functions_per_file": [3, 4, 4, 0, 2],
  "lines_per_function": {
    "min": 2, "max": 24, "mean": 11.2, "p95": 24
  },
  "docstring_coverage": 0.2308,
  "type_annotation_depth": 1.0,
  "test_to_source_ratio": 2.168,
  "try_except_total": 0,
  "import_total": 12
}
```

## Adding a new language

1. Create a fixture under `fixtures/coding/<name>/` (fixed types + stubs + tests)
2. Create scenario JSON in `suites/coding/<name>.json`
3. The auto-detector in `coding-tests.py` should detect it automatically
4. If not, add a new detection clause + runner function in `coding-tests.py`

## Batch Ingestion Style Probe (reference fixture)

`fixtures/coding/batch-ingestion/` — Python data pipeline probe:

| File | Stubs | Fixed? |
|---|---|---|
| `pipeline/types.py` | — | YES — dataclasses (Record, ValidationError, etc.) |
| `pipeline/validate.py` | `validate_record()`, `validate_batch()` | Signatures fixed |
| `pipeline/transform.py` | `normalize_payload()`, `flatten_payload()`, `transform_batch()` | Signatures fixed |
| `pipeline/filter.py` | `FilterRule`, `matches_filter_rule()`, `apply_filters()` | Sig + FilterRule fixed |
| `pipeline/aggregate.py` | `group_by_type()`, `summarize_type()`, `aggregate_batch()` | Signatures fixed |
| `tests/test_*.py` | — | YES — 49 tests total |

Scenario JSON: `suites/coding/batch-ingestion-python.json`
Scorers declared: `["coding-tests", "structure-metrics", "latency"]`
