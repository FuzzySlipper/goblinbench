# GoblinBench

A Den/Hermes-oriented model and agent evaluation lab.

GoblinBench answers recurring operational questions:

- Which model/service should back the Den Vision Analyzer capability?
- Which model/profile is suitable for orchestration and planning decisions?
- Which coding agents perform best on realistic maintenance tasks?
- Which models are fast/cheap/good enough for a given role as releases churn?

> **Entrypoint for agents:** the runner is `python3 scripts/gb-run.py`. The
> canonical results store is `runs/goblinbench.sqlite` (committed; it's the
> backup). See **[Quick start](#quick-start)** and
> **[CLI reference](#cli-reference)**. Python is the only in-repo runner path;
> the old .NET implementation was removed after the port.

## Architecture

GoblinBench is built around four core concepts:

### Scenario

A **Scenario** is a versioned evaluation case. It supplies inputs, fixture setup, expected behavior, and scoring configuration. Scenarios live as JSON files under `suites/<suite>/` (e.g. `suites/orchestrator/malformed-completion-packet.json`).

Suite categories:
- `orchestrator` — workflow decision-making, worker claim validation
- `coding` — maintenance/style tasks against copied fixtures (Python/Go/Rust/TS)
- `mcp-tools` / `mcp-tools-hard` — fake-MCP tool-use behavior
- `mcp-session` — multi-turn durable tool-use sessions
- `autonomy-calibration` / `evidence-grounding` — fuzzy autonomy + groundedness
- `vision` — UI screenshot analysis
- `den-mcp-ambiguity` (+ `-hinted`) — tool-vs-doc disambiguation
- `fake-den-mcp` — scripted fake-MCP catalog scenarios
- `tool-call-behavior` — argument grounding + optional-parameter traps
- `demo` — smoke scenarios
- `electron` — Electron GUI harness (Playwright path is stubbed; effectively dormant)

### Candidate

A **Candidate** is what is being evaluated, defined in `candidates.json`:

- An **OpenAI-compatible chat model** (plain chat, or specialized via `cli_command`/`config.runner`: `mcp-openai-tool-use`, `fuzzy-openai`, `mcp-openai-session`, `vision-openai`)
- A **bwrap-sandboxed coding agent** (`kind: CodingAgent` — launches `pi`/codex/claude inside a sandbox against a copied fixture)
- A **deterministic scripted candidate** for smoke-testing (`cli_command: scripted` / `fake-mcp-scripted` / `fuzzy-scripted` / `coding-scripted` / `noop`)

Candidates track model/provider/config separately from prompt/profile/runtime so comparisons are clean.

### Runner

A **Runner** prepares fixtures, invokes the candidate, collects output/traces/artifacts, and hands the result to scorers. Runner implementations are registered per candidate kind in `scripts/gb/registry.py` (first-match dispatch). See [`docs/python-runner.md`](docs/python-runner.md) for the full runner audit.

### Scorer

A **Scorer** evaluates candidate output against expected behavior. Scorers are either in-process Python (`scripts/gb/scorers/`) or external plugins invoked by `gb-score.py` (`scripts/scorers/`).

| Scorer ID | Kind | Notes |
|---|---|---|
| `latency` | metadata | Duration + optional cost estimate. Always informational. |
| `schema-compliance` | deterministic | Required fields + types vs a JSON schema |
| `orchestrator-decision` | deterministic | action/confidence/reason/arrays check |
| `mcp-tool-use` | deterministic | expected calls + argument grounding + forbidden tools + recovery |
| `mcp-session-trajectory` | deterministic | per-turn tool expectations across a multi-turn session |
| `fuzzy-agent-behavior` | deterministic | decision label + action boundary + grounding + question specificity |
| `vision-correctness` | deterministic | answer + elements + hallucination-risk + structure |
| `exact-decision` | deterministic | Exact JSON-value match against expected |
| `heuristic-text` | heuristic | Forbidden markers (TODO/FIXME/…) + required patterns |
| `noop` | deterministic | Always passes (smoke harness) |
| `coding-tests` | command | Plugin (`scripts/scorers/coding-tests.py`); multilingual test runner |
| `structure-metrics` | heuristic | Plugin; per-file LOC / function / type-annotation depth |
| `maintainability-metrics` | heuristic | Plugin; changed-file mass + deltas |

## Project layout

```
scripts/
  gb-run.py                 Runner entrypoint + main loop (the primary CLI)
  gb-store.py               Canonical store control (import / list / delete / report)
  gb-report.py              Static HTML report generator (LLM-friendly)
  gb-score.py               Post-run scorer-plugin pipeline (merges coding-tests etc.)
  gb-results.py             Legacy query CLI (still works; gb-store is the green path)
  gb/                       The runner package (models, runners, scorers, store, report)
    store.py                Canonical SQLite store (runs/goblinbench.sqlite)
    report/                 HTML report tool + views (grid / failures / cell)
suites/                     Scenario definitions (JSON), grouped by suite
candidates.json             Candidate definitions (72 candidates)
fixtures/                   Fixture sources (copied per-run by coding runners)
runs/                       Run artifacts (ring-buffered; gitignored)
  goblinbench.sqlite        Canonical results store (committed — the backup)
tests/                      Python tests for runner/store/reporting behavior
docs/                       Documentation
```

## Quick start

### Prerequisites

- Python 3.10+ (stdlib only — no venv or pip install needed for the runner itself)
- `bwrap` (bubblewrap) for the coding-agent sandbox path
- Toolchains per fixture language when running coding scenarios (python/pytest, go, cargo, node — only the ones you exercise)

### Run a scenario

```bash
# Deterministic smoke (no model calls) — the fastest green-path check
python3 scripts/gb-run.py --suite orchestrator --candidate scripted-deterministic

# Real coding-agent hot path (bwrap-sandboxed pi against a copied fixture)
# Maintainability mini-service probes currently exist for Python, TypeScript, Go, and Rust.
python3 scripts/gb-run.py \
  --scenario coding.maintainability-mini-service-python \
  --candidate pi-coding-glm52-den-router
python3 scripts/gb-run.py \
  --scenario coding.maintainability-mini-service-typescript \
  --candidate pi-coding-glm52-den-router
python3 scripts/gb-run.py \
  --scenario coding.maintainability-mini-service-go \
  --candidate pi-coding-glm52-den-router
python3 scripts/gb-run.py \
  --scenario coding.maintainability-mini-service-rust \
  --candidate pi-coding-glm52-den-router

# Filter by suite / scenario / candidate (repeatable, comma-separated)
python3 scripts/gb-run.py --suite coding --candidate pi-coding-glm52-den-router,pi-coding-gpt4o
python3 scripts/gb-run.py --suite mcp-tools --skip-scenario mcp-tools.dodgy-roster-lookup
```

Each run writes `runs/<run-id>/` (scenarios → candidates → artifacts), then auto-ingests into the canonical store. Common filters: `--suite`, `--scenario`, `--candidate`, `--candidates <path>`, `--skip-scenario` / `--exclude-scenario`.

### Look at the results

```bash
# What's in the store?
python3 scripts/gb-store.py status
python3 scripts/gb-store.py list

# One run's cells + per-cell pass/fail
python3 scripts/gb-store.py get <run-id>

# Generate an HTML report (the LLM-friendly surface — narrative goes in the lede)
python3 scripts/gb-report.py --suite coding --view grid \
  --narrative "Comparing coding models on the maintainability fixture." \
  --out /tmp/grid.html
python3 scripts/gb-report.py --runs <run-id> --view failures --out /tmp/failures.html
python3 scripts/gb-report.py --model glm52 --view cell --out /tmp/cell.html
```

## CLI reference

| Command | Role |
|---|---|
| `scripts/gb-run.py` | **Run scenarios against candidates.** Writes `runs/<id>/` + ingests into the store. |
| `scripts/gb-store.py` | **Manage the canonical store.** `status` / `list` / `get` / `import` / `delete` / `label` / `prune` / `vacuum`. See [`docs/storage-and-reporting.md`](docs/storage-and-reporting.md). |
| `scripts/gb-report.py` | **Generate static HTML reports.** Views: `grid` (model×scenario), `failures` (triage), `cell` (deep-dive). Narrative slot for LLM prose. |
| `scripts/gb-score.py` | **Post-run scorer pipeline.** Runs the `scripts/scorers/*.py` plugins (coding-tests, structure-metrics, maintainability-metrics) and merges results back into `run.json`. Auto-invoked by `gb-run.py`. |
| `scripts/gb-results.py` | Legacy query CLI over the old `goblinbench-results.sqlite` index. Still works for ad-hoc SQL-style queries; `gb-store` is the maintained path going forward. |

## Output structure

Each run produces:

```
runs/<run-id>/
  run.json                    Overall run result (scenarios, per-cell results, scores)
  scenarios/<scenario-id>/
    candidates/<candidate-id>/
      output.json             Raw candidate output
      scores.json             Per-scorer evaluation results
      trace.jsonl             Execution trace events
      artifacts/              Scorer/runner auxiliary artifacts
      fixture/                (coding runs) copied fixture the agent edited
      stdout.log stderr.log   (coding-agent runs) filtered agent streams
      agent.patch             (coding-agent runs) unified diff of agent edits
```

On-disk run files are **ring-buffered** (the N most recent are kept; older dirs auto-pruned — see `gb-store prune --keep`). The **canonical record is `runs/goblinbench.sqlite`**, which holds run metadata, scores, scorer detail, inline artifacts (patches/code/score breakdowns), and representative samples. See [`docs/storage-and-reporting.md`](docs/storage-and-reporting.md).

## Score result fields

Every score includes:
- `scoring_kind` — classification: `deterministic`, `heuristic`, `command`, `llm_judge`, `human`, `metadata`
- `score` — numeric score (higher is better)
- `passed` — whether the score meets the configured threshold
- `human_summary` — concise one-line summary for reports
- `judge_model` / `judge_prompt_version` — for LLM judges only (the `llm-judge` scorer is currently a placeholder, 0 scenario uses)

## License

Proprietary — internal use only.
