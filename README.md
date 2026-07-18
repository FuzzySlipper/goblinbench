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

See **[Test menu](#test-menu)** for the current suite chooser and exact
scenario IDs.

### Candidate

A **Candidate** is what is being evaluated, defined in `candidates.json`:

- An **OpenAI-compatible chat model** (plain chat, or specialized via `cli_command`/`config.runner`: `mcp-openai-tool-use`, `fuzzy-openai`, `mcp-openai-session`, `vision-openai`)
- A **Codex app-server agent** or **Rusty Crew agent** (external-session and
  native-brain paths, with debug-service-only candidates for test isolation)
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
| `codebase-analysis-gold` | deterministic | Gold-ledger recall, evidence quality, severity calibration, and decoy penalties for architecture review |
| `vision-correctness` | deterministic | answer + elements + hallucination-risk + structure |
| `exact-decision` | deterministic | Exact JSON-value match against expected |
| `heuristic-text` | heuristic | Forbidden markers (TODO/FIXME/…) + required patterns |
| `noop` | deterministic | Always passes (smoke harness) |
| `coding-tests` | command | Plugin (`scripts/scorers/coding-tests.py`); multilingual test runner |
| `structure-metrics` | heuristic | Plugin; per-file LOC / function / type-annotation depth |
| `maintainability-metrics` | heuristic | Plugin; changed-file mass + deltas |
| `architecture-quality` | heuristic | Hard-fixture penalties for centralization, seam loss, dependency direction, oversized central functions, and duplication; reported separately from behavioral tests. |
| `asha-governance` | deterministic | Mixed Rust/TypeScript authority, replay, generated-contract, ownership-boundary, policy/projection, and guidance gates for the Mini ASHA coding fixture. |

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
candidates.json             Default candidate definitions (83 candidates)
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

# Filter by suite / scenario / tag / candidate (repeatable, comma-separated)
python3 scripts/gb-run.py --suite coding --candidate pi-coding-glm52-den-router,pi-coding-gpt4o
python3 scripts/gb-run.py --suite coding --tag hard --tag rust --candidate pi-coding-glm52-den-router
python3 scripts/gb-run.py --suite mcp-tools --skip-scenario mcp-tools.dodgy-roster-lookup
```

Each run writes `runs/<run-id>/` (scenarios → candidates → artifacts), then auto-ingests into the canonical store. Common filters: `--suite`, `--scenario`, `--tag` (all supplied tags must match), `--candidate`, `--candidates <path>`, `--skip-scenario` / `--exclude-scenario`.

If a late provider failure occurred after a coding agent already edited its
scratch fixture, the native runner now retains the diff and fixture path so
normal post-scorers can still measure the code while the cell keeps its
`runner_error`/`timeout` provenance. Older retained runs can be repaired without
another model call:

```bash
python3 scripts/gb-score.py runs/<run-id> \
  --retry-failed --refresh-in-process
python3 scripts/gb-store.py import --run-json runs/<run-id>/run.json
```

`--retry-failed` replaces only failed script-scorer invocations.
`--refresh-in-process` re-runs the maintained fuzzy and codebase-analysis
scorers, including bounded malformed-JSON recovery. Raw responses and runner
success/error fields are not rewritten.

## Test menu

The current inventory is **94 scenarios across 19 suites**. Use a suite when
you want the whole family, or copy an exact scenario ID from the catalog below.

```bash
# Whole suite
python3 scripts/gb-run.py --suite <suite> --candidate <candidate-id>

# One exact test
python3 scripts/gb-run.py --scenario <scenario-id> --candidate <candidate-id>

# Candidate matrix stored outside the default candidates.json
python3 scripts/gb-run.py --suite <suite> \
  --candidates <candidate-file.json>
```

### Which suite should I use?

| Suite | Tests | Use it to measure |
|---|---:|---|
| `autonomy-calibration` | 3 | Whether an agent acts, asks, or blocks at the right boundary; includes real bounded tool-use and no-bypass cases. |
| `evidence-grounding` | 3 | Hallucination resistance, explicit unknowns, and separation of self-report from verified evidence. |
| `codebase-analysis` | 1 | Hard read-only architecture review with planted issues, evidence requirements, and valid-pattern decoys. |
| `coding` | 22 | Real fixture edits, including hard Rust systems probes, an extended TypeScript architecture probe, and the governed mixed-language Mini ASHA feature. |
| `coding-smoke` | 1 | Deterministic offline end-to-end coding-runner smoke. |
| `orchestrator` | 8 | Workflow decisions under incomplete, conflicting, stale, or blocking worker/review evidence. |
| `mcp-tools` | 8 | Single-turn fake-MCP selection, argument grounding, recovery, safe writes, and refusal when no valid capability exists. |
| `mcp-tools-hard` | 3 | Large decoy-heavy tool forests with evidence gathering and narrow write/refusal boundaries. |
| `mcp-session` | 1 | Multi-turn durable tool-use behavior and whether a model learns a boundary across turns. |
| `tool-call-behavior` | 4 | Optional-argument minimalism and recovery from bare versus guided tool errors. |
| `den-mcp-ambiguity` | 6 | Den project/document/task routing without extra hints. |
| `den-mcp-ambiguity-hinted` | 6 | The same Den routing cases with improved tool-description hints for A/B comparison. |
| `fake-den-mcp` | 1 | Read-versus-write selection in a compact Den-shaped tool forest. |
| `roleplay-prose` | 7 | Default prose quality versus anti-slop prompting across dialogue, movement, atmosphere, and subtext. |
| `roleplay-instruction` | 1 | Rich roleplay prose without controlling the user's character. |
| `roleplay-heat-boundary` | 4 | Behavior across PG-13 through explicit-adult heat levels, including user-character agency. |
| `vision` | 12 | Screenshot description, text/state extraction, clutter handling, next actions, and absent-element hallucinations. |
| `electron` | 2 | Electron UI automation; one Linux Playwright smoke and one Windows/FlaUI native-dialog test. |
| `demo` | 1 | Deterministic end-to-end runner/scorer/artifact smoke with no model call. |

### Exact scenario IDs

<details>
<summary><code>autonomy-calibration</code> — 3 scenarios</summary>

- `autonomy-calibration.clear-smoke-test-after-patch` — run and ground a bounded local smoke test without a permission loop.
- `autonomy-calibration.mcp-tool-limitation-bypass-script` — do not script around a missing or mismatched MCP capability.
- `autonomy-calibration.two-source-repo-conflict` — ask a concrete question when Den and local repo notes conflict.

</details>

<details>
<summary><code>evidence-grounding</code> — 3 scenarios</summary>

- `evidence-grounding.model-capability-incomplete-logs` — avoid a full leaderboard when benchmark evidence is incomplete.
- `evidence-grounding.partial-thread-status-brief` — preserve unknown verification and closure state from a partial thread.
- `evidence-grounding.self-report-vs-review-packet` — distinguish worker self-report from reviewed/promoted evidence.

</details>

<details>
<summary><code>codebase-analysis</code> — 1 scenario</summary>

- `codebase-analysis.den-core-v1` — hard read-only synthetic repository review with 12 planted issues and four valid-pattern decoys; gold and decoy ledgers are never copied into the candidate workspace.

</details>

<details>
<summary><code>coding</code> — 22 scenarios</summary>

- `coding.batch-ingestion-python` — Python fixed-interface implementation and structural-style probe.
- `coding.batch-ingestion-typescript` — TypeScript fixed-interface implementation and structural-style probe.
- `coding.batch-ingestion-go` — Go fixed-interface implementation and structural-style probe.
- `coding.batch-ingestion-rust` — Rust fixed-interface implementation and structural-style probe.
- `coding.maintainability-mini-service-python` — Python architecture-pressure baseline.
- `coding.maintainability-mini-service-python-style-guided` — Python with concise seam-preservation guidance.
- `coding.maintainability-mini-service-python-style-prose-guided` — Python with longer maintainability guidance.
- `coding.maintainability-mini-service-typescript` — TypeScript architecture-pressure baseline.
- `coding.maintainability-mini-service-typescript-style-guided` — TypeScript with concise seam-preservation guidance.
- `coding.maintainability-mini-service-typescript-style-prose-guided` — TypeScript with longer maintainability guidance.
- `coding.maintainability-mini-service-go` — Go architecture-pressure baseline.
- `coding.maintainability-mini-service-go-style-guided` — Go with concise seam-preservation guidance.
- `coding.maintainability-mini-service-go-style-prose-guided` — Go with longer maintainability guidance.
- `coding.maintainability-mini-service-rust` — Rust architecture-pressure baseline.
- `coding.maintainability-mini-service-rust-style-guided` — Rust with concise seam-preservation guidance.
- `coding.maintainability-mini-service-rust-style-prose-guided` — Rust with longer maintainability guidance.
- `coding.leased-dag-queue-rust` — hard Rust atomic DAG admission, lease fencing, retry, cancellation, and dependency-state propagation.
- `coding.framed-replica-rust` — hard Rust incremental framing, corruption recovery, sequence idempotency, and transactional replica state.
- `coding.durable-workflow-engine-typescript` — hard non-frontend TypeScript workflow/persistence/eventing architecture baseline.
- `coding.durable-workflow-engine-typescript-style-guided` — the exact TypeScript fixture/tests with concise seam-preservation guidance.
- `coding.durable-workflow-engine-typescript-style-prose-guided` — the exact TypeScript fixture/tests with extended backend-architecture prose.
- `coding.asha-authority-door` — mixed Rust/TypeScript authoritative feature with replay, codegen, dependency ownership, and Asha-style governance gates.

</details>

<details>
<summary><code>coding-smoke</code> — 1 scenario</summary>

- `e2e-pi-mock` — deterministic offline Pi coding-agent end-to-end test.

</details>

<details>
<summary><code>orchestrator</code> — 8 scenarios</summary>

- `orchestrator.ambiguous-wake-evidence` — contradictory completion status and exit code.
- `orchestrator.malformed-completion-packet` — completion packet missing required handoff fields.
- `orchestrator.retry-loop-risk` — repeated identical failure that should not be retried blindly.
- `orchestrator.review-finding-triage` — nonfunctional review issue: block or follow-up.
- `orchestrator.reviewer-blocking-bug` — critical reviewer finding that must block.
- `orchestrator.stale-branch-mismatch` — worker head no longer matches the branch.
- `orchestrator.success-but-missing-tests` — success claim without required test artifacts.
- `orchestrator.unresolved-dependency` — queue pressure must not bypass a dependency.

</details>

<details>
<summary><code>mcp-tools</code> and <code>mcp-tools-hard</code> — 11 scenarios</summary>

- `mcp-tools.buggy-stale-inventory` — detect stale data and use the recheck tool.
- `mcp-tools.conflicting-tool-descriptions` — prefer explicit schema and safety constraints.
- `mcp-tools.customer-case-summary` — plain read-only multi-tool lookup.
- `mcp-tools.dodgy-roster-lookup` — choose by schema despite imprecise tool names.
- `mcp-tools.http-temptation-no-bypass` — do not use an HTTP-shaped bypass tool.
- `mcp-tools.impossible-bank-transfer` — refuse an unavailable external side effect.
- `mcp-tools.malformed-tool-result` — do not fabricate fields missing from a malformed result.
- `mcp-tools.safe-write-confirmation` — validate context before the scoped write.
- `mcp-tools-hard.canary-rollout-forest` — combine rollout and incident evidence before one write.
- `mcp-tools-hard.invoice-payment-forest` — avoid payment decoys and create only a review draft.
- `mcp-tools-hard.prod-archive-forest` — gather evidence, then refuse a production archive.

</details>

<details>
<summary><code>mcp-session</code>, <code>tool-call-behavior</code>, and <code>fake-den-mcp</code> — 6 scenarios</summary>

- `mcp-session.archive-boundary-lesson` — learn archive boundaries over a durable multi-turn session.
- `tool-call-behavior.bare-error-recovery-control` — recovery after a bare validation error.
- `tool-call-behavior.guided-error-recovery` — recovery using a tool-provided correction hint.
- `tool-call-behavior.null-optional-write-trap` — avoid null and empty optional write parameters.
- `tool-call-behavior.optional-parameter-minimalism` — omit unneeded optional arguments.
- `fake-den-mcp.task-read-vs-update` — read task details without taking tempting write actions.

</details>

<details>
<summary><code>den-mcp-ambiguity</code> — 6 baseline + 6 hinted scenarios</summary>

Each base ID below also has an otherwise equivalent hinted ID under
`den-mcp-ambiguity-hinted.*`.

- `den-mcp-ambiguity.clarify-destructive-doc-action` — clarify archive versus comment.
- `den-mcp-ambiguity.comment-vs-update-document` — comment without overwriting the document.
- `den-mcp-ambiguity.den-mcp-doc-system-planner` — keep an explicit Den MCP document target.
- `den-mcp-ambiguity.persona-not-project-task-message` — do not treat a persona as a project ID.
- `den-mcp-ambiguity.project-explicit-report-doc` — honor the explicitly named project.
- `den-mcp-ambiguity.search-vs-get-document` — search a fuzzy title before exact retrieval.
- `den-mcp-ambiguity-hinted.clarify-destructive-doc-action`
- `den-mcp-ambiguity-hinted.comment-vs-update-document`
- `den-mcp-ambiguity-hinted.den-mcp-doc-system-planner`
- `den-mcp-ambiguity-hinted.persona-not-project-task-message`
- `den-mcp-ambiguity-hinted.project-explicit-report-doc`
- `den-mcp-ambiguity-hinted.search-vs-get-document`

</details>

<details>
<summary><code>roleplay-prose</code>, <code>roleplay-instruction</code>, and <code>roleplay-heat-boundary</code> — 12 scenarios</summary>

- `roleplay-prose.orbital-maintenance-v0` — movement, spatial clarity, and tension.
- `roleplay-prose.orbital-maintenance-v1` — the same scene with anti-slop guidance.
- `roleplay-prose.rainy-inn-doorway-minimal-v0` — low-instruction default prose tendencies.
- `roleplay-prose.rainy-inn-doorway-v0` — restrained sensory and character prose.
- `roleplay-prose.rainy-inn-doorway-v1` — the same scene with anti-slop guidance.
- `roleplay-prose.train-platform-subtext-v0` — restrained dialogue and subtext.
- `roleplay-prose.train-platform-subtext-v1` — the same scene with anti-slop guidance.
- `roleplay-instruction.no-user-control-reliquary-v0` — write the scene without controlling the user character.
- `roleplay-heat-boundary.pg13-balcony-kiss-v0` — PG-13 sensuality without over-refusal or overshoot.
- `roleplay-heat-boundary.r-soft-bedroom-v0` — mature soft-focus romance.
- `roleplay-heat-boundary.nc17-explicit-consenting-adults-v0` — explicit consenting-adult boundary behavior.
- `roleplay-heat-boundary.nc17-no-user-control-v0` — explicit boundary plus user-character agency.

</details>

<details>
<summary><code>vision</code> — 12 scenarios</summary>

- `vision.absent-element-hallucination` — do not invent absent UI elements.
- `vision.compare-ui-states` — compare expected and actual panels.
- `vision.describe-busy-dashboard` — describe an overlapping, cluttered dashboard.
- `vision.describe-chaotic-desk` — dense inventory, spatial coverage, and uncertainty.
- `vision.describe-map-board` — topology, labels, routes, and alerts.
- `vision.describe-warehouse-shelf` — grouped inventory and visible labels under occlusion.
- `vision.disabled-controls` — distinguish enabled and disabled controls.
- `vision.identify-error-banner` — detect and read a visible alert.
- `vision.inspect-game-hud-low-health-chaos` — extract border HUD state through combat clutter.
- `vision.inspect-game-hud-overheat-chaos` — extract mech status through noisy labels.
- `vision.read-modal-state` — identify modal purpose and dismissal requirements.
- `vision.suggest-next-action` — choose the likely next interaction from the screenshot.

</details>

<details>
<summary><code>electron</code> and <code>demo</code> — 3 scenarios</summary>

- `electron.hello-launch-and-echo` — Linux-capable Playwright launch/type/echo smoke.
- `electron.native-dialog-save` — Windows/FlaUI native Save dialog verification.
- `demo-noop` — deterministic runner, scorer, and artifact smoke without a model.

</details>

### Common candidate menus

| Candidate file | What it is for |
|---|---|
| `candidates.json` | Default broad catalog used when `--candidates` is omitted. |
| `candidates.rusty-crew-native-gpt56.json` | Native Rusty Crew matrix for GPT-5.6 Luna, Terra, and Sol via `rusty-crew-debug.service`. |
| `candidates.rusty-crew-native-gpt56-medium.json` | The same native GPT-5.6 trio with an intentional, verified session-level `medium` reasoning override. |
| `candidates.rusty-crew-native-smoke.json` | One inexpensive native Rusty Crew smoke candidate. |
| `candidates.codex-rusty-crew-comparison.json` | Direct Codex app-server versus Rusty Crew comparison pair. |
| `candidates.codex-rusty-crew-luna-comparison.json` | Luna-specific direct versus Rusty Crew comparison pair. |
| `candidates.codex-app-server-smoke.json` | Direct Codex app-server smoke candidate. |
| `candidates.gpt56-reasoning-fuzzy.json` | GPT-5.6 model × effort matrix for autonomy and grounding tests. |
| `candidates.gpt56-reasoning-mcp.json` | GPT-5.6 model × effort matrix for single-turn MCP tests. |
| `candidates.gpt56-reasoning-session.json` | GPT-5.6 model × effort matrix for durable MCP sessions. |
| `candidates.denrouter-requested-fuzzy.json` | Requested Den-router matrix for autonomy and grounding suites. |
| `candidates.denrouter-requested-mcp.json` | Requested Den-router matrix for MCP tool suites. |
| `candidates.denrouter-requested-session.json` | Requested Den-router matrix for durable MCP sessions. |
| `candidates.roleplay-matrix.json` | Combined roleplay comparison matrix. |
| `candidates.roleplay-denrouter.json` | Den-router roleplay candidates. |
| `candidates.roleplay-local.json` / `candidates.roleplay-lemonade.json` | Local roleplay candidates. |

Rusty Crew benchmark candidates must use `rusty-crew-debug.service`; do not
point smoke or comparison runs at the live service. The native GPT-5.6 matrix
leaves temperature and output-token limits to the provider registration and
only applies a reasoning-effort override when a candidate explicitly requests
one.

The checked-in core campaign runs Luna, Terra, and Sol at explicit medium
effort over autonomy calibration, evidence grounding, the Go/TypeScript/Rust
maintainability baselines, and codebase architecture analysis. It intentionally
excludes fake-MCP suites until Rusty Crew has a provider-neutral native adapter:

```bash
# Inspect the exact 30-cell command without starting model calls
python3 scripts/run-rusty-crew-gpt56-medium-core.py --dry-run

# Run all 10 scenarios x 3 models through rusty-crew-debug.service
python3 scripts/run-rusty-crew-gpt56-medium-core.py
```

The hard coding campaign is the better tier-differentiation pass. Its default is
9 cells: two Rust systems tasks plus the unguided TypeScript backend task across
Luna, Terra, and Sol at medium effort. The TypeScript prompt variants use the
same canonical fixture and tests, so `--all-style-variants` isolates prompt
influence instead of changing required behavior.

```bash
# Exact default hard campaign, without model calls
python3 scripts/run-rusty-crew-gpt56-medium-hard.py --dry-run

# Rust-only: 2 scenarios x 3 models
python3 scripts/run-rusty-crew-gpt56-medium-hard.py --language rust

# TypeScript baseline only: 1 scenario x 3 models
python3 scripts/run-rusty-crew-gpt56-medium-hard.py --language typescript

# TypeScript baseline + concise + prose: 3 scenarios x 3 models
python3 scripts/run-rusty-crew-gpt56-medium-hard.py \
  --language typescript --all-style-variants

# All five hard scenarios x 3 models
python3 scripts/run-rusty-crew-gpt56-medium-hard.py --all-style-variants
```

All hard scenarios carry `hard`, language, routing, and architecture-pressure
tags; use the exact IDs above for ad-hoc subsets. `coding-tests` is the strict
behavior gate. `architecture-quality` is a separate 0–1 score, so a behaviorally
correct but centralized implementation remains visible as an architectural
penalty instead of being mislabeled as a test failure.

The Mini ASHA scenario is the governed cross-language interview probe. It uses
its own `asha-governance` scorer because one generic language test command
cannot represent Rust authority, replay, generated TypeScript contracts,
ownership edges, policy restraint, and projection boundaries independently:

```bash
python3 scripts/gb-run.py \
  --scenario coding.asha-authority-door \
  --candidates candidates.rusty-crew-native-gpt56-medium.json
```

The scorer hashes guidance, governance, manifests, CI, and visible tests;
overlays hidden regressions in a temporary copy; reports eight weighted gates;
and caps the result when any critical authority or boundary gate fails.

The generic runner can also select the hard language subsets without the
campaign wrapper:

```bash
python3 scripts/gb-run.py --suite coding --tag hard --tag rust \
  --candidates candidates.rusty-crew-native-gpt56-medium.json
python3 scripts/gb-run.py --suite coding --tag hard --tag typescript \
  --candidates candidates.rusty-crew-native-gpt56-medium.json
```

## Look at the results

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
python3 scripts/gb-report.py --runs <run-id> --view environment --out /tmp/environments.html
```

## CLI reference

| Command | Role |
|---|---|
| `scripts/gb-run.py` | **Run scenarios against candidates.** Writes `runs/<id>/` + ingests into the store. |
| `scripts/gb-store.py` | **Manage the canonical store.** `status` / `list` / `get` / `import` / `delete` / `label` / `prune` / `vacuum`. See [`docs/storage-and-reporting.md`](docs/storage-and-reporting.md). |
| `scripts/gb-report.py` | **Generate static HTML reports.** Views: `grid` (candidate×scenario, lane-separated), `failures` (triage), `cell` (deep-dive), `environment` (provenance/cost comparison). Narrative slot for LLM prose. |
| `scripts/gb-score.py` | **Post-run scorer pipeline.** Runs the `scripts/scorers/*.py` plugins (including coding-tests, architecture-quality, structure-metrics, and maintainability-metrics) and merges results back into `run.json`. Auto-invoked by `gb-run.py`. |
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
