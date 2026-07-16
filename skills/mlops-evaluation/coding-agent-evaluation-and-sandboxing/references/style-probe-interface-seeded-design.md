# Interface-Seeded Style Probes — Measuring Training-Data Gravity

## Problem

Existing coding scenarios (tree-prune, kth-selection, roman-numerals, etc.) are
**correctness probes** — they test whether an agent can fix a single-file bug.
When populated, every model writes essentially the same ~30-80 line fix. There
is zero stylistic signal to measure.

The naive alternative (open-ended "build an app") produces wildly different
architectures per run — model A produces 3 files, model B produces 12, no two
share the same module boundaries. Cross-model comparison is impossible.

## Solution: Interface-Seeded Style Probes

**Fix the file boundaries and function signatures; free the implementation bodies.**

Provide a multi-file project where:
- `types.py` / `types.ts` / `types.rs` — fixed data structures (NOT modified by agent)
- `impl files` — function signatures only, agent fills bodies
- `tests/` — fixed test suite that passes on any correct implementation

This gives you:
- **Fixed N files** — cross-model comparison is apples-to-apples
- **Fixed M function signatures** — you know what each file is supposed to do
- **Free implementation bodies** — the agent's natural style has room to express itself
  (function size, type annotation depth, docstring density, error handling patterns,
  test coverage, import style)

The result is a *comparable structural canvas* with stylistic variation inside each cell.

## Design Principles

### 1. Size sweet spot: "Batch processing module" level

Too small (single-function fix) → no style variance.
Too large (full service/app) → architecture varies, ruins comparison.

Right size: **3-5 implementation files, 2-3 functions per file, ~150-250 total impl LOC.**
This is large enough for structural habits to manifest, small enough that the
*correct* decomposition is unambiguous.

### 2. Language-native interfaces

Port the same logical problem to each language using its native idioms:
- **Python** — dataclasses, Protocol, pytest fixtures
- **TypeScript** — interfaces, vitest, Set/Map
- **Rust** — structs with derives, Result types, cargo test, `#[cfg(test)]`

The interface files must use language-native patterns — not translated C#.
The gravity signal IS the difference between a Python model writing 40-line
functions with sparse types vs a Rust model writing 8-line functions with
explicit error propagation on the same problem.

### 3. Tests constrain correctness only, not style

Test files are fixed and must pass with *any* correct implementation. They should:
- Test each function in isolation (unit tests)
- Test pipeline integration
- Assert immutability (input records not mutated)
- Assert order preservation
- Cover edge cases (empty input, all removed, no change)

They should NOT assert:
- Line count / function size / number of helper functions
- Specific algorithm or approach (within correctness bounds)
- Comment style or docstring presence

### 4. What varies (the gravity signal)

The structure-metrics scorer captures these:

| Metric | What it measures | Expected gravity range |
|---|---|---|
| Lines per function (mean, p95) | Compact vs sprawling function bodies | Python: 10-25, TS: 8-18, Rust: 5-12 |
| Type annotation depth | % of params + returns typed | Python: 0.3-1.0, TS: 0.8-1.0, Rust: 1.0 |
| Docstring coverage | % of functions with docstrings | Python: 0.1-0.8, TS: 0-0.5, Rust: 0-0.3 |
| Test-to-source ratio | test LOC / impl LOC | Varies by model culture |
| Try/except count | Error handling density | Python: 0-5, Rust: via Result (different metric) |
| Import verbosity | Explicit per-name vs wildcard | Python culture has both |

## Reference Implementation: Batch Ingestion Pipeline

Location: `fixtures/coding/batch-ingestion/` (Python)
Scenario: `suites/coding/batch-ingestion-python.json`
Scorer: `scripts/structure-metrics.py`

The probe implements a data pipeline with four stages:
1. **validate** — record validation rules
2. **transform** — payload normalization + flattening
3. **filter** — rule-based filtering
4. **aggregate** — group-by-type summarization

Each stage has a dedicated file with 2-3 function signatures and ~8-15 tests.
The `types.py` file (dataclasses) is fixed and must not be modified.

### Verified properties (reference solution)

- 49 tests, all pass in ~0.03s
- 13 functions across 5 impl files
- 256 impl LOC, 555 test LOC
- 2.17 test-to-source ratio
- 100% type annotation depth
- 23% docstring coverage
- 0 try/except blocks
- 12 import statements

## Integration with Coding-Agent Runner

The Python batch-ingestion scenario configures:
```json
{
  "scoring": {
    "scorers": ["coding-tests", "structure-metrics", "latency"],
    "parameters": {
      "coding-tests": {
        "test_project": "python-pytest",
        "scan_dir": "pipeline",
        "timeout_seconds": 60
      },
      "structure-metrics": {
        "scan_dir": "pipeline"
      }
    }
  }
}
```

The `test_project: "python-pytest"` signals to the runner that it should use
`python -m pytest` instead of `dotnet test`. Currently only the dotnet scorer
is implemented in the runner — the python-pytest scorer needs a wiring change
before this scenario can be run via the harness directly.

For manual scoring: `scripts/score-batch-ingestion.sh`

## Task Design for the Future

When creating new style probes, prefer this pattern over translating existing
C# scenarios:

1. Pick a **domain** that has natural multi-file decomposition (pipeline, service, processor, converter)
2. Write the **interface files** first — they determine the decomposition
3. Write the **test files** — they must pass with any correct implementation
4. Write the **impl stubs** — function signatures with docstrings and `...` bodies
5. **Validate** by filling a reference solution and running tests
6. **Reset** impl stubs to empty bodies

The TypeScript and Rust ports should follow the same logical design with
language-native type/error idioms rather than direct transcriptions.
