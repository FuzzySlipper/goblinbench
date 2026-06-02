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
- Exact/structured decision matching
- Test/build result validation (`dotnet test`, Playwright)
- Static heuristics (TODO/FIXME/HACK markers)
- Rubric/LLM judge evaluation
- Latency/cost/schema compliance
- Visual analysis
- Human override

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

## License

Proprietary — internal use only.
