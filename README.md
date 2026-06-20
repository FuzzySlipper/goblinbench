# GoblinBench

A Den/Hermes-oriented model and agent evaluation lab.

GoblinBench answers recurring operational questions:

- Which model/service should back the Den Vision Analyzer capability?
- Which model/profile is suitable for orchestration and planning decisions?
- Which coding agents perform best on realistic maintenance tasks?
- Which models are fast/cheap/good enough for a given role as releases churn?

## Architecture

GoblinBench is built around four core concepts:

### Scenario

A **Scenario** is a versioned evaluation case. It supplies inputs, fixture setup, expected behavior, and scoring configuration. Scenarios live as JSON files under `suites/<suite>/`.

Example suite categories:
- `vision` — UI screenshots, error banners, modal/dialog state
- `orchestrator` — workflow decision-making, worker claim validation
- `coding` — maintenance tasks, PR review, test generation
- `electron-gui` — Electron app testing with Playwright/FlaUI

### Candidate

A **Candidate** is what is being evaluated. It can be:
- An OpenAI-compatible chat model
- A Hermes profile launched via spawned Hermes
- A Den capability service endpoint
- An external coding CLI (Codex, Claude Code, OpenCode)
- A local model endpoint (vLLM, llama.cpp)

Candidates track model/provider/config separately from prompt/profile/runtime so comparisons are clean.

### Runner

A **Runner** prepares fixtures, invokes the candidate, collects output/traces/artifacts, and hands the result to scorers. Runner implementations are registered per candidate kind.

### Scorer

A **Scorer** evaluates candidate output against expected behavior. Scorers are pluggable and can include:

| Scorer | ID | Kind | Description |
|---|---|---|---|
| Exact Decision | `exact-decision` | deterministic | Matches candidate output fields against expected values |
| Schema Compliance | `schema-compliance` | deterministic | Validates output against a JSON schema (required fields, types) |
| Heuristic Text | `heuristic-text` | heuristic | Checks for forbidden markers (TODO, FIXME, HACK) and required patterns |
| Command / Test | `command` | command | Shells out to deterministic commands, checks exit codes and stdout |
| Latency / Cost | `latency` | metadata | Records duration and estimates cost from pricing config |
| LLM / Rubric Judge | `llm-judge` | llm_judge | Placeholder for LLM-based evaluation with judge model/prompt version tracking |

#### Deterministic vs LLM-judge scoring

- **Deterministic scorers** (`exact-decision`, `schema-compliance`, `command`, `heuristic-text`, `latency`) produce reproducible results without external API calls. Use these for CI-aligned, fast, cost-free evaluation.
- **LLM-judge scorers** (`llm-judge`) use an external model to evaluate qualitative aspects. Always record the judge model and prompt version in the score result for reproducibility.

#### Tracking judge model and prompt version

When using an LLM judge, configure it in the scenario's scoring config:

```json
{
  "scoring": {
    "scorers": ["llm-judge"],
    "judges": {
      "llm-judge": {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_version": "v2",
        "temperature": 0.0
      }
    }
  }
}
```

The score result records `judge_model` and `judge_prompt_version` so every evaluation is traceable.

#### Score result fields

Every score includes:
- `scoring_kind` — classification: `deterministic`, `heuristic`, `command`, `llm_judge`, `human`, `metadata`
- `score` — numeric score (higher is better)
- `passed` — whether the score meets the configured threshold
- `human_summary` — concise one-line summary for reports
- `judge_model` / `judge_prompt_version` — for LLM judges only

## Project layout

```
src/
  GoblinBench.Core/        — Domain models and interfaces
  GoblinBench.Runner/      — CLI harness entry point
  GoblinBench.Candidates/  — Candidate runner implementations
  GoblinBench.Scorers/     — Scorer implementations
suites/                    — Scenario definitions (JSON)
  demo/                    — Demo/smoke-test scenarios
runs/                      — Run artifacts (gitignored)
docs/                      — Documentation
```

## Quick start

### Prerequisites

- .NET SDK 10.0 or later

### Build

```bash
dotnet build
```

### Run tests

```bash
dotnet test
```

### Run the demo scenario

```bash
dotnet run --project src/GoblinBench.Runner
```

This discovers scenarios under `suites/`, runs the default no-op candidate, and writes artifacts to `runs/<run-id>/`.

#### Python runner (in progress)

A drop-in Python port of the runner is available alongside the .NET one. It writes
the same `runs/<run-id>/` artifact tree, so `gb-score.py` and `gb-results.py`
consume it unchanged. All three milestones are complete: every candidate (72/72)
and every scenario-declared scorer is handled in pure Python. See
[`docs/python-runner.md`](docs/python-runner.md).

```bash
python3 scripts/gb-run.py --suite orchestrator --candidate scripted-deterministic
```

### Output structure

```
runs/<run-id>/
  run.json                    — Overall run result with scenario and candidate summaries
  candidates/
    <candidate-id>/
      output.json             — Raw candidate output
      trace.jsonl             — Execution trace events
      scores.json             — Per-scorer evaluation results
      artifacts/              — Candidate-produced files
```

### Fast results index / CLI

For cross-run comparisons, build the SQLite results index and query it with the lightweight CLI:

```bash
scripts/gb-results.py import --reset
scripts/gb-results.py compare --suite den-mcp-ambiguity --by model
scripts/gb-results.py model glm --by scenario
scripts/gb-results.py coverage --suite coding --model qwenmax
scripts/gb-results.py failures --model minimax --limit 20
```

The database at `runs/goblinbench-results.sqlite` is a rebuildable index over raw run artifacts. See `docs/results-cli.md` for commands, output formats, and agent-friendly usage patterns.

## License

Proprietary — internal use only.
