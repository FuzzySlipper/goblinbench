---
name: coding-agent-evaluation-and-sandboxing
description: "Use when building, porting, debugging, or verifying coding-agent evaluation harnesses, fixture suites, fake-tool/MCP benchmarks, candidate runners, result reports, low-trust subprocess sandboxes for agent CLIs or model-driven tools, and scoring pipeline architecture (Python post-processing pipeline reading .NET run.json)."
version: 1.7.0
author: GoblinOverseer
license: MIT
metadata:
  hermes:
    tags: [coding-agents, evaluation, benchmarks, sandboxes, bwrap, fixtures, goblinbench]
    related_skills: [test-driven-development, systematic-debugging, den-mcp]
---

# Coding-Agent Evaluation and Sandboxing

This umbrella skill covers the full class of work around evaluating coding agents and running low-trust agent/tool subprocesses safely: benchmark harnesses, scenario fixtures, visible/strict tests, fake-tool and fake-MCP suites, local/cloud candidate runners, result artifacts, and bubblewrap-style sandboxing.

Use this instead of a one-session skill about a specific GoblinBench import, local model comparison, bwrap failure, or mock OpenAI server quirk. Session-specific detail belongs in `references/`; statically reusable probes and mocks live in `scripts/`; candidate/provider starter files live in `templates/`.

## When to Use

- Porting legacy coding tasks into a benchmark harness.
- Designing fixtures, visible/strict tests, scoring thresholds, or result reports.
- Wiring no-op/scripted/local/cloud candidates and comparing model behavior.
- Building fake-tool, fake-MCP, groundedness, autonomy, or orchestrator suites.
- Launching coding agents/model CLIs against disposable workspaces and capturing diffs.
- Using Linux `bwrap`/bubblewrap to make destructive accidents hard while preserving enough reads/network access for realistic evaluation.
- Comparing models exposed through the den router (`http://127.0.0.1:18082/v1`) — see `references/den-router-candidate-comparison.md` for the candidate-config layout, smoke probe, and reasoning-model budgeting gotchas.\n- Running the codebase analysis Mode A benchmark (task #1929) — see `references/codebase-analysis-benchmark-methodology.md` for the full design pattern (gold-ledger, decoys, packet generation, scoring rubric, report format, known pitfalls). Use `scripts/generate-packet.py` to regenerate a packet with full source code inline — **critical: do NOT include issue-hinting prose in the packet** (the first run with a hint-leaking packet produced 2x inflated scores: DeepSeek Flash 83% vs 42% on real code). The `scripts/codebase-analysis-runner.py` script handles run, judge, and report generation. For large-packet benchmarks (72KB+), increase `urlopen` timeout from 300s to 600s and set judge `max_tokens` to 16384. The runner now includes a `MODEL_TEMPS` dict for per-model temperature constraints (kimi-code requires 1.0).
- Comparing local models served by Lemonade Server (`http://192.168.1.23:13305/v1`) — see `references/lemonade-direct-api-local-model-comparison.md` for direct-API candidate config, quant-level comparison pairs, cold-start timing, and smoke-test patterns.
- Running medium/high reasoning-effort A/B branches for expensive GPT-ish models in complex agentic fitness suites — see `references/gpt56-reasoning-effort-matrix-2026-07-09.md` for Patch's preference to treat model selection as the low-effort path, candidate naming, runner support, smoke probes, and old+new report merge pattern.
- Building qualitative long-form prose / roleplay comparison campaigns — see `references/roleplay-prose-qualitative-benchmark-2026-07-07.md` for the SillyTavern-avoidance pattern, `roleplay-prose` suite shape, anti-slop prompt variants, Lemonade Gemma 4 thinking-mode request override, and Markdown artifact workflow.
- Building visual-inspect / chaotic screenshot description model matrices — see `references/visual-inspect-candidate-matrix.md` for direct Lemonade vs den-router routing, candidate IDs, no-key local endpoint behavior, and pre-matrix smoke checks.

Do **not** use this as a hostile-actor containment recipe. For adversarial isolation, use a real container/firejail/seccomp profile and a security review.

## Core Harness Workflow

1. **Start from durable task state.** If Den-tracked, create/update the Den task and progress there first.
2. **Preserve upstream fidelity.** Keep original prompt/ticket text, source URL/commit, fixture provenance, and normalization notes in scenario metadata.
3. **Port fixtures as runnable workspaces.** Each scenario should have starter source, visible tests, strict tests, project/build files, and optional known-good patch.
4. **Verify with deterministic candidates first.** Use a no-op/scripted/fake candidate before spending model time. Confirm fixture builds, test filters, baseline broken-starter shape, and scoring artifacts.
5. **Smoke-test cloud-routed candidates before adding them to `candidates.json`.** `/v1/models` lists names the den router is willing to *route* to upstream, not names that will *answer*. A 4-token `curl` POST to `/v1/chat/completions` catches 404s, reasoning-model token burn, and auth issues in seconds. **Also test with `temperature` set** — some models (e.g. kimi) reject non-1.0 temperature with HTTP 400, which the basic smoke probe (no temperature) won't catch. **Use a temp file for the JSON payload** (`curl -d @tmpfile`) rather than inline JSON in the shell command — shell quoting silently mangles payloads and produces false-negative smoke results. See `references/den-router-candidate-comparison.md`.
6. **Run real candidates only after harness health is clean.** Model time should test model behavior, not harness wiring.
7. **For local model matrix runs, warm the cache first.** Smoke-test all local candidates (Lemonade, local vLLM) with a simple `max_tokens: 16` probe before starting the matrix run. This pays the cold-start cost once instead of inside a timed scenario. Order candidates smallest-first in the matrix script so early runs complete quickly. See `references/lemonade-direct-api-local-model-comparison.md` for observed cold-start times.
7. **Separate enabling slices from suite completion.** After restarts or handoffs, verify the Den parent task, subtasks, repo artifacts, and tests before answering "is this done?" A catalog/generator/fixture smoke slice may unblock the suite without satisfying the full acceptance criteria (for example real candidate runs, named regressions, scoring dimensions, and reports).
8. **Separate runner health from scoring health.** A timeout-killed agent may leave a useful patch that scores nonzero; report process status separately from test-score status.
9. **Capture interpretable artifacts.** Preserve model/provider, candidate config, prompt/scenario/harness versions, command, environment, pass counts, score, exit status, logs, diffs, and artifact paths.
10. **Bound live protocol artifacts before running real agents.** For WebSocket/SSE/app-server/MCP-style runners, raw event logs, pending notifications, and assistant deltas must have independent byte/count limits. Stream complete raw events to JSONL; retain only bounded summaries in memory. Use separate acknowledgement and turn-completion deadlines, preserve a partial workspace snapshot on limit/deadline failure, and report it as a runner/substrate failure rather than allowing a stuck stream to consume host memory. A pending JSON-RPC request must read new socket frames directly rather than draining/re-queueing preserved notifications, or one notification can spin forever and defeat the bounds. Validate live recovery smokes in a separately memory-capped transient scope, not by changing the shared agent service. See `references/long-lived-agent-event-stream-safety.md` and `references/app-server-protocol-and-scoring-safety.md`.
11. **Prefer flat scannable comparisons over dense reports.** When the user asks for results, deliver compact per-scenario tables with pass/fail and latency, not multi-section markdown with narrative. Dense reports are fine for artifacts, but the user-facing summary should be a table they can scan in seconds.
11. **For prose-heavy qualitative campaigns, use the qualitative Markdown report path.** Run normal GoblinBench scenarios/candidates first so outputs land in `runs/goblinbench.sqlite`, then use `python3 scripts/gb-qual-report.py --runs <run-id> --suite <suite> --dry-run` to inspect judge packets, iterate `templates/qualitative-judge-v1.md` or `--rubric-file`, and finally call a separate judge via `--judge-provider/--judge-model` or `--judge-candidate`. This writes repeatable campaign artifacts (`judge-template.md`, `rubric.md`, per-scenario judge requests/responses, `judgements.json`, and an external `qualitative-report.md`). Default judge labels are blinded A/B/C; use `--no-blind` only when the judge should see model IDs. For roleplay/prose comparisons, include both low-instruction/default-tendency probes and heavy-handed anti-slop/instruction-following traps; report output chars, reasoning chars, and finish reason separately when testing thinking mode. Plain OpenAI chat candidates support `reasoning_effort`, `include_temperature_with_reasoning_effort`, `chat_template_kwargs`, and `request_overrides` in candidate `config`; long-thinking local models need generous `timeout_seconds` (e.g. 900s) plus high `max_tokens`. For adult-romance boundary testing, use a direct heat ladder (PG-13 → soft R → NC-17 → NC-17 + no-user-control), make the consenting-adult fictional setup unambiguous, explicitly allow plain refusal, and classify boundary behavior separately from prose quality; prefer the deterministic `roleplay-heat-boundary` scorer first, with classification-only judge prompts/redaction only if needed. Run large roleplay matrices in provider splits (e.g. den-router first, Lemonade second) rather than one mixed slog; summarize with a flat per-candidate dial table before dense side-by-side output artifacts. For qualitative judge passes over adult-roleplay outputs, smoke one scenario first and require parseable JSON before launching the full set: Kimi/Kimi-code can be uncensored as candidates but may burn the judge budget in reasoning and return empty `content` on large comparison prompts; Grok produced parseable public-summary judgements for the 2026-07 heat-boundary run. Treat tiny-token smoke failures from thinking models as inconclusive when `finish_reason=length` and content is empty — retry with a larger smoke budget before declaring the candidate unroutable.
12. **Use the canonical store/report CLIs for cross-run questions.** Current GoblinBench green path is `scripts/gb-store.py` for status/list/get/import/delete/label/prune over `runs/goblinbench.sqlite`, `scripts/gb-report.py` for static HTML grid/failures/cell reports, and `scripts/gb-qual-report.py` for qualitative Markdown comparison artifacts. `scripts/gb-results.py` is legacy and still useful for older SQL-style ad hoc queries, but do not prefer it for routine reporting. The on-disk `runs/run-*` trees are ring-buffered scratch; the committed SQLite store is the durable record.
13. **Make shareable public report artifacts summary-first.** For model comparisons intended for non-agent readers (e.g. roleplay users / ST community), do not just point at raw `runs/` trees or GitHub `blob` URLs. Generate a compact Markdown/HTML summary first, keep full outputs behind links/details, and publish via a real static host such as GitHub Pages. Patch's preferred current path is the `den-web` shared-pages publisher (`/home/dev/den-web/tools/scripts/publish_static_page.py`, npm alias `npm run publish:page -- ...`), which renders Markdown reports into `pages/<slug>/`, updates a landing index, copies source files under `source/`, and strips active HTML/script from model-generated Markdown. Keep classification/quality caveats visible at the top. When publishing multiple campaign artifacts, duplicate source basenames are common (`qualitative-report.md` from two directories); ensure the publisher/version in use preserves both with suffixed names like `qualitative-report-2.html` rather than overwriting.
14. **When a replacement runner is verified, remove dead legacy paths rather than leaving them as “reference” code.** Patch prefers a single clear current path for agents. After deleting a legacy tree, immediately update repo-root detection, docs, scenario prompts, scorer branches, and tests that assumed it existed; scan for stale command strings before reporting. See `references/goblinbench-python-only-runner-cleanup-2026-06-21.md` for the GoblinBench cleanup checklist.
13. **Report task-shape insight.** Use failure categories and task-shape tags so reports reveal which models fit which work, not just aggregate win rates.

## Vision / Visual-Inspect Description Suites

For GoblinBench vision scenarios that evaluate screenshot understanding rather than coding agents:

- Use `cli_command: "vision-openai"` candidates for OpenAI-compatible multimodal calls; run `scripted-deterministic` first to validate scenario/scorer plumbing.
- Existing binary/UI checks use `vision-correctness` with the compact `elements_found`/`answer` schema.
- Chaotic or dense screenshot description tests should use scenario-level `input.response_schema = "vision_description_v1"` so one vision candidate can run both old UI verdict scenarios and richer description-quality scenarios without candidate duplication.
- Back each chaotic fixture with a manifest containing required mentions, regions, forbidden claims, relationship expectations, visible text, and ambiguous items; score with `vision-description-quality` so vague summaries, forbidden hallucinations, missed salient regions, and poor spatial grounding produce distinct failure categories.
- Generate deterministic synthetic fixtures before realistic/generated images. Synthetic fixtures give exact gold manifests and allow deterministic scripted smoke runs before spending model calls.
- For wordy/reasoning vision models, prefer a generous response budget (`max_tokens: 8192` worked for the 2026-06-25 matrix) when the goal is comparison signal; strict cost tuning can come after the model emits usable structured responses.
- Direct Lemonade Server on den-nimo (`http://192.168.1.23:13305/v1`) can be used as a no-key OpenAI-compatible vision endpoint; den-router is optional for local models unless central routing/accounting is needed. Den-router cloud baselines use the same `vision-openai` runner. Kimi-family den-router models may still require `temperature: 1.0`.
- Report runner/HTTP success, strict JSON/schema compliance, and visual content quality separately. A model that produces visually useful text with invalid JSON should be called a structured-output failure, not automatically a visual-understanding failure.
- If a long matrix run is silent because Python stdout is buffered, inspect incremental artifacts under `runs/<run>/scenarios/<scenario>/candidates/<candidate>/scores.json` and `output.json` before killing it.
- For `visual-inspect` service benchmarking, keep compatibility with the service contract: screenshots + criteria/context/options in; `pass|fail|uncertain`, confidence, criteria results, observations/regions, follow-up hints, model info, and warnings out. Direct GoblinBench scenarios may use a richer intermediate description schema as long as scorer/report fields map back to that contract.
- See `references/vision-chaotic-description-matrix-2026-06-25.md` for the first 9-model chaotic-description matrix, candidate configs, JSON-format pitfalls, and fixture-hardening recommendations.
- For harder HUD-over-chaos tests, use `references/vision-hud-chaos-distractor-pattern.md`: deterministic PIL center-noise + crisp border HUD, `distractor_mentions` manifests, and separate focus/distractor-resistance reporting.
- For deployed `visual-inspect` service tuning with local Gemma4, use `references/visual-inspect-deployed-gemma4-tuning-2026-06-26.md`: direct raw-provider reproduction for `model_output_invalid`, strict JSON prompt contract fixes, token/timeout budget, fail-vs-uncertain wording, auth smoke, and artifact-root gotchas.

## Fixture and Scenario Checklist

- Fixture source is copied into a per-run workspace; original fixtures remain immutable.
- Visible and strict tests are selectable by stable filters such as namespace or traits.
- Scoring config names the test project explicitly when multiple projects exist.
- Marker scans target the source directory candidates are expected to edit.
- Threshold semantics match benchmark intent; use full-pass semantics when partial credit is misleading.
- Scenario metadata includes upstream prompt/source references.
- Candidate artifacts are scenario-scoped, e.g. `runs/<run>/scenarios/<scenario-id>/candidates/<candidate-id>/...`, never a shared per-candidate directory that accumulates state across scenarios.
- For A/B comparisons (e.g. baseline vs hinted tool descriptions), keep the same scenario shape; vary only the variable under test; tag with `tool_description_variant` or equivalent so reports can group runs by variant.

## Interface-Seeded Style Probes (Training-Data Gravity)

A new scenario class for measuring **training-data gravity** — the inherent
stylistic bias each model has for different languages, absent any controlling
signals.

### The Observability Problem

Existing coding scenarios are single-file bug-fix correctness probes — every
model writes the same ~30-80 line fix, producing zero stylistic signal.
Open-ended "build an app" tasks produce wildly different architectures per run,
making cross-model comparison impossible.

### Interface-Seeded Approach

**Fix the file boundaries and function signatures; free the implementation bodies.**

Provide a multi-file project where:
- `types.*` — fixed data structures (NOT modified by agent)
- Implementation files — function signatures only, agent fills bodies
- Tests — fixed suite that passes on any correct implementation

This gives fixed-N-files for apple-to-apple comparison with free-internal-style
for visible gravity signal.

### Design Principles

1. **Size sweet spot**: 3-5 impl files, 2-3 functions each, ~150-250 total impl LOC
2. **Language-native interfaces**: same logical problem, native idioms per language
   (Python dataclasses + pytest, TS interfaces + vitest, Rust structs + cargo test)
3. **Tests constrain correctness, not style**: test I/O, edge cases, immutability,
   order preservation. Do NOT assert line count, algorithm choice, or docstring presence
4. **The gravity signal** comes from structure metrics: lines/function, type annotation
   depth, docstring coverage, test-to-source ratio, error handling density, import style

### Reference Implementation

The **Batch Ingestion Pipeline** style probe implements the same 4-stage record processor
(validate → transform → filter → aggregate) across multiple languages:
- Python: `fixtures/coding/batch-ingestion/` (`49` pytest tests)
- TypeScript: `fixtures/coding/batch-ingestion-ts/` (`51` Vitest tests)
- Go: `fixtures/coding/batch-ingestion-go/` (`50` Go tests)
- Rust: `fixtures/coding/batch-ingestion-rust/` (`50` Cargo integration tests)

First same-model trials with `pi-coding-deepseek-flash-den-router` passed all four ports.
Style metrics should count **agent-editable implementation files only**: exclude fixed
interface/type files such as `types.py` / `types.ts` / `types.go` / `types.rs` / `lib.rs` and
generated runner/test artifacts such as `__pycache__`, `.pytest_cache`, `.venv`, `uv.lock`,
`node_modules`, `coverage`, `dist`, and Cargo `target` from diffs and metrics. See
`references/style-probe-interface-seeded-design.md` for methodology and
`goblinbench/batch-ingestion-python-typescript-go-rust-style-probe-trial-1` for the first
4-language result table.

### Maintainability-Pressure Style Probes

The **Maintainability Mini-Service** probe is the sibling benchmark family for
architecture/godfile pressure. Current fixtures:
- Python: `fixtures/coding/maintainability-mini-service-python/` with scenario
  `coding.maintainability-mini-service-python`
- TypeScript: `fixtures/coding/maintainability-mini-service-ts/` with scenario
  `coding.maintainability-mini-service-typescript`
- Go: `fixtures/coding/maintainability-mini-service-go/` with scenario
  `coding.maintainability-mini-service-go`
- Rust: `fixtures/coding/maintainability-mini-service-rust/` with scenario
  `coding.maintainability-mini-service-rust`

Shape:
- Tiny in-memory service with router/container/auth/validation/repository/audit/handler seams.
- One tempting central handler/router path.
- Cross-cutting feature: `POST /customers/bulk-import` touches auth, validation, persistence,
  audit, and response shaping.
- Behavior tests assert correctness only; architecture is observed by metrics after the fact.

Scorer:
- `scripts/maintainability-metrics.py` compares current source to
  `.goblinbench/maintainability-baseline.json` stored in the fixture.
- Wrapper: `scripts/scorers/maintainability-metrics.py`.
- The scorer supports Python AST metrics plus lightweight TypeScript/JS, Go, and Rust text metrics.
- Scenario `maintainability-metrics` parameters must set the language's source root and path
  groups, e.g. Python `service/...`, TypeScript/Rust `src/...`, or Go root-level `*.go` central/setup/handler paths.
- `structure-metrics` scenarios should set `scan_dir` explicitly. The scorer wrapper honors this; if a row shows unexpected Rust/TS test files as impl files, check `scripts/scorers/structure-metrics.py` before trusting that style row.
- Signals include changed-file concentration, central changed-mass share, central/setup/handler
  line deltas, largest function growth, handler max LOC, public API/import deltas,
  doc/comment/readability proxies, and identifier generic/meaningful ratios.

First Python baseline (`pi-coding-deepseek-flash-den-router`, run `run-20260620-043126-0fe09be9`):
correctness passed (`10/10`) but the whole feature landed in `service/handlers/customers.py`,
with 100% central changed-mass share and `bulk_import_customers` growing to 67 LOC. This is the
intended distinction: behavior success vs maintainability pressure. Full note:
`goblinbench/maintainability-mini-service-python-baseline-1`.

First TypeScript trial (`pi-coding-deepseek-flash-den-router`, run `run-20260621-051347-cec759dd`):
correctness passed (`10/10`) but the feature landed entirely in `src/handlers/customers.ts`,
with 100% central changed-mass share, largest-function Δ +43, and handler max 64 LOC. Use this
as the canonical example of reporting behavior success separately from architecture/style pressure.
Session detail: `references/maintainability-mini-service-typescript-2026-06-21.md`.

First full matrix (`deepseek-pro`, `glm52`, `stepfun`, `minimax`, `qwen-max`, `kimi-code`
across Python/TypeScript/Go/Rust): see
`references/maintainability-mini-service-matrix-2026-06-21.md` and Den doc
`goblinbench/maintainability-mini-service-matrix-6-models-4-languages`. Run language-at-a-time
batches rather than all 24 cells concurrently because pi coding-agent den-router candidates share
sandbox/workspace plumbing. Report a flat table first. Main observed style signal: Python converged
all models into the handler; GLM52 split TypeScript and Go into helper files; Minimax split Go but
timed out and failed compile on Rust salvage; most other cells stayed central-handler heavy.

For multi-model maintainability matrices, prefer language-at-a-time sequential batches and exact
den-router model ID validation before launching. See
`references/maintainability-matrix-language-batch-pattern.md` for the wrapper pattern,
qwen/kimi candidate-ID gotcha, smoke probes, progress monitoring, and flat reporting shape.
When importing a single completed run into the canonical store, use the current CLI shape
`python3 scripts/gb-store.py import --run-json runs/<run-id>/run.json`; do not pass the run id
as a positional argument.
For prompt-style A/B/C comparisons, see
`references/maintainability-mini-service-prose-style-guidance-2026-06-22.md`: report token
columns separately (`input`, `output`, `input+output`, `cacheRead`, `total`, `calls`) because
cache-read-heavy tool loops distort total tokens, and expect prose guidance to change style
non-monotonically rather than simply increasing seam-splitting.

For style-prompt A/B/C maintainability matrices, keep prompt variants as separate scenarios and
report token columns separately (`input`, `output`, `cacheRead`, `cacheWrite`, `totalTokens`,
`calls`) rather than a single total. This avoids misreading cache-heavy tool-loop churn as pure
model dithering. See `references/maintainability-style-prompt-variants-2026-06-22.md` for the
prose-style-guided variant pattern, DeepSeek Flash inclusion, token reporting shape, and
interpretation pitfalls.

### Structure-Metrics Scorer

`scripts/structure-metrics.py` is a standalone AST-based analyzer that measures
structural properties of a completed impl directory. Run standalone:
```
python3 scripts/structure-metrics.py <implementation_dir> [--output results.json]
```
Emits: file count, LOC per file, function count, lines/function distribution,
docstring coverage, type annotation depth, test-to-source ratio, try/except count,
import count. Designed to work with any language that has Python AST coverage
(targets Python impls; TS/Rust variants would need language-specific parsers).

## Fake Tool / MCP / Groundedness Suites

- Keep deterministic runner/scorer paths separate from real-model runners.
- For OpenAI-compatible fake tools, map scenario-owned fake tools to `chat/completions` `tools`, execute requested tool calls against canned fake results, append `role: "tool"` messages, and save request/response dumps plus `chat_transcript.json`.
- **Fake-tool contract fidelity is mandatory for hard suites.** Do not grade hidden required arguments that were absent from the advertised JSON Schema. Give every tool properties, required fields, useful descriptions, and explicit `additionalProperties` behavior. Before a live model run, statically compare every scripted expected argument against the tool schema: classify non-required fields as either a safe default (remove it from the canned expectation), a declared semantic matcher/free-text effect, or an intentional task-grounding constraint. Validate an agent call before consuming/returning its canned result; never return success solely because the tool name matches and later penalize the same call for its arguments. The direct OpenAI fake-tool path and stdio/HTTP fake-MCP path must invoke the same validation/fixture-state contract. An advertised decoy with no scripted behavior must return a structured unavailable/unsupported result—not synthetic success—so an agent can recover without being falsely rewarded. Prefer isolated stateful fake services and final-state scoring for complex tasks over one exact hidden tool sequence. See `references/fake-tool-contract-audit-2026-07-11.md` for the audit checklist and regression pattern.
- **Separate protocol failure from near-pass.** Reports should preserve raw/average score, hard safety violations, schema/argument mismatch, recoverable validation error, optional-field stuffing, and final-state failure separately. A binary pass-rate cell must not make a 0.75 near-pass indistinguishable from an unsafe forbidden tool call.
- **Judge completeness is part of benchmark validity.** For judge-scored outputs, detect truncation/invalid JSON/partial fallback extraction and label the evaluation `judge_incomplete` rather than converting partial judged findings into 0% recall. Chunk large candidate finding sets, retry malformed judge output, and preserve raw judge artifacts. Treat bonus-findings, planted-ledger recall, false positives, and evidence quality as separate metrics.
- For live Den MCP schema catalogs, do not broaden the active Hermes profile/toolset just to inspect tool definitions. Query the streamable HTTP MCP endpoint with `initialize` + `tools/list`, parse SSE `data:` JSON, sort tools deterministically, and pin the result as a fixture artifact; see `references/streamable-http-den-mcp-catalog-refresh.md`.
- When a raw MCP facade exposes unprefixed tool names but the eval should mimic Hermes-facing names, apply a deterministic generator transform such as `--name-prefix mcp_den_` before filtering/scoring rather than loading every tool into context.
- Include impossible-task and forbidden-bypass cases early.
- Harden suites with tool forests: 10+ plausible tools, near-miss schemas, decoys, and strict grounding thresholds.
- For durable multi-turn suites, preserve chat history and score trajectory properties like `passed_turn_count`, `forbidden_tool_use_count`, and `no_calls_violation_count`.
- For fuzzy autonomy/groundedness, keep runner output small and scorer-friendly: `decision_label`, `question`, `actions_taken`, `claims[{text,support}]`, `unknowns`, and `final_response`.
- When scoring project/tool routing, prefer direct argument-field checks for fields like `project_id`, `slug`, and `task_id`; do not let a wrong field value pass merely because the expected project/id appears elsewhere in freeform `content` or the final answer. Add explicit failure categories for hallucinated project/persona routing and unnecessary/missing clarification.
- **A/B tool-description comparisons (baseline vs hinted), generate separate reports per variant and merge externally — the report generator deduplicates by candidate ID and will silently drop the second variant's results if both are passed to a single report invocation. See `references/den-router-candidate-comparison.md` for the multi-round merge pattern.
- **Orchestrator suites require different candidates than MCP suites.** Scenarios that target `suites/orchestrator/` are decision-making prompts with `available_actions` but no `fake_mcp.tools`. Running them through an MCP-focused candidate (`cli_command: mcp-openai-tool-use`, `config.runner: mcp-openai-tool-use`) causes `OpenAiMcpToolUseRunner` to reject them instantly ("no input.fake_mcp.tools entries"). Create separate orchestrator-safe candidate entries (no `cli_command`, no `config.runner` — these let `OpenAiChatRunner` handle plain chat). See `references/den-router-candidate-comparison.md` for the pattern.
- **Interpret orchestrator/coding-agent failures by evidence, not just score.** A 0.00 FAIL can mean: (a) HTTP 502/503 from den-router (infra, re-run), (b) timeout/token exhaustion on a reasoning model (raise time/token budget or tune reasoning effort), (c) coding-agent substrate failure (e.g. pi/node exit 137 with no patch), or (d) genuine wrong action (real model failure). Check logs, latency, raw/retained stdout sizes, whether tool/final messages exist, and whether a source patch exists before classifying. For subprocess coding agents, also replay the exact generated argv outside the parent runner when possible: if `bwrap_argv` succeeds from a Python/shell parent but fails under `.NET CodingAgentRunner`, treat the issue as parent-process supervision/capture/lifecycle until proven otherwise. When the Python runner (`scripts/gb-run.py`) is available, validate the same candidate/scenario there and confirm downstream compatibility with `gb-results.py import` + `cell` before judging model quality. See `references/orchestrator-suite-sanity-vs-discrimination.md`, `references/pi-glm52-dotnet-supervision-investigation-2026-06-20.md`, and `references/python-runner-glm52-validation-2026-06-20.md`.
- For orchestrator-suitability fake-MCP suites, add A/B tool-description variants when investigating whether failures are model capability vs schema affordance. Keep prompts, fake tool results, expected calls, and thresholds identical; change only tool descriptions/schema field descriptions (e.g. `TOOL HINT:` guidance for project routing, persona-vs-project language, destructive-action clarification) so pass-rate deltas are interpretable. The `den-mcp-ambiguity` / `den-mcp-ambiguity-hinted` pair is the working example; see `references/den-router-candidate-comparison.md` for the A/B run pattern.
- Reasoning models (e.g. `kimi`, `mimo` via den router) consume `max_tokens` on internal `reasoning_content` before tool calls. The runner does not surface this; budget `max_tokens >= 4096` (prefer 8192 for reasoning models) for tool-use suites and record `finish_reason` in the run report so reasoning-vs-non-reasoning model comparisons are interpretable.
- **Model-specific parameter constraints:** some upstream models reject parameters the OpenAI API normally accepts. Notable: `kimi` via den router requires `temperature: 1.0` (HTTP 400 on any other value). After a basic smoke probe, do a second probe that includes `temperature` to catch these before scheduling a full matrix run. See `references/den-router-candidate-comparison.md` for the per-model constraint table.
- **Reasoning effort tuning:** the `OpenAiMcpToolUseRunner` supports an optional `reasoning_effort` config field (values: `"low"`, `"medium"`, `"high"`). When set, it sends `reasoning_effort` instead of `temperature` in the API request — some reasoning models reject temperature != 1 when reasoning_effort is present. Create separate candidate entries suffixed `-re-low` / `-re-medium` / `-re-high` for effort-variant runs. For Patch's complex agentic-fitness evaluations on expensive GPT-ish reasoning models, do **not** default to low as the meaningful branch: Patch generally uses model selection (StepFun/local/etc.) as the low-effort path, so medium and high are the useful comparison branches. Report effort variants as separate rows, never silently collapsed into one model row. Experimental finding from earlier MCP runs: reasoning effort can be a minor knob for tool discipline (±1 pass), weaker than tool-description hints (±2-3 passes), but GPT-family models may hard-swing enough to justify explicit medium/high branches. See `references/den-router-candidate-comparison.md` and `references/gpt56-reasoning-effort-matrix-2026-07-09.md` for config patterns and runner support gotchas.
- **Tool discipline is orthogonal to raw capability.** SOTA models (Opus 4.8) can score *worse* than cheap models (StepFun Step 3.7 Flash) on restraint/framework-fit scenarios because they over-act instead of asking for clarification. When selecting orchestrator models, prioritize tool-discipline benchmarks over coding benchmarks. The `den-mcp-ambiguity` suite's `clarify-destructive-doc-action` scenario is a particularly discriminating test.
- **A/B report generation:** when running baseline + hinted variants, pass them to separate `report` invocations with the matching `--suite` filter (`den-mcp-ambiguity` vs `den-mcp-ambiguity-hinted`). Candidate IDs are identical across variants; a single report with the wrong suite filter silently drops the other variant's runs.
- **Fuzzy/grounding scenario input contamination:** `fake_tools` and `scripted_tool_calls` in `scenario.input` cause chat models to emit tool calls instead of decision packets, even when the prompt explicitly asks for structured JSON. **Strip these keys** from `autonomy-calibration` and `evidence-grounding` scenarios before running live models. The scenario is a decision-making test, not a tool-use test. Leaving them in produces uniform 0.00 scores that look like model failure but are actually a prompt-injection artifact.
- **Ground-truth nesting gotcha:** `expected_behavior` and `scripted_decision_packet` in these suites live under `scenario.input`, not at the top level. When checking for them programmatically, look in `scenario.input.expected_behavior` / `scenario.input.scripted_decision_packet`, not `scenario.expected_behavior`.
- **SSE-whitespace response quirk:** some OpenRouter-proxied models (notably `stepfun`, `hy3`) return HTTP 200 with JSON bodies prefixed by SSE-style whitespace. Standard `json.loads()` fails on the raw response. Strip to the first `{` before parsing in ad-hoc smoke probes. The GoblinBench runner handles this internally.

## Runner Flags

- `--skip-scenario <id>` — exclude one scenario from the run (repeatable).
- `--exclude-scenario <id>` — alias for `--skip-scenario`.
- `--suite`, `--scenario`, `--candidate` — inclusion filters.
- Skip filters are applied after suite/scenario inclusion, so `--suite coding --skip-scenario coding.roman-numerals` works as expected.
- The runner prints the skip list in the run header when `--skip-scenario` is used.

## Coding Suite Runner Constraints

The coding suite is **not** a generic chat benchmark. It requires candidates that can execute code against a disposable workspace. The runner enforces this through `CodingCandidateRunner` and `CodingAgentRunner`:

- **Accepted:** `cli_command: "coding-scripted"` (scripted/deterministic) or `kind: "CodingAgent"` (real CLI like pi)
- **Rejected (SKIP):** plain OpenAI chat candidates (`kind: "OpenAiModel"`, `cli_command: "mcp-openai-tool-use"`) — `OpenAiChatRunner` cannot satisfy the coding scorer’s workspace/test execution contract

**Practical implication:** you cannot run `suites/coding/*` against den-router chat candidates directly. Options:
1. Add pi-style `CodingAgent` candidates with a pi extension that routes through den-router (same pattern as Lemonade local runs).
2. Use pi with `--provider den-router --model <name>` and a custom `models.json` pointing at `127.0.0.1:18082/v1`.
3. Build a dedicated coding-runner wrapper for chat models (more work, not yet implemented).

The `/home/dev/den-pi/extensions/den-router.ts` extension auto-registers a `den-router` provider by fetching `/v1/models` from `http://127.0.0.1:18082` and maps every model id into pi’s provider model list. A pi coding-agent candidate can therefore be wired to any den-router model by pointing `--extension` at that file and `--provider den-router --model <id>`, without hand-editing a `models.json`.

Recommended den-router coding candidate config (sandboxed):
```json
{
  "id": "pi-coding-<model>-den-router",
  "kind": "CodingAgent",
  "model": "<model-id>",
  "provider": "den-router",
  "cli_args": [
    "--print", "--no-session",
    "--no-extensions",
    "--extension", "<abs-path-to-den-router.ts>",
    "--provider", "den-router",
    "--model", "<model-id>",
    "--mode", "json"
  ],
  "config": {
    "agent_resolved": "/<abs>/.sandbox-runtime/node_modules/@earendil-works/pi-coding-agent/dist/cli.js",
    "sandbox_root": "/<abs>/.sandbox-runtime",
    "node_resolved": "/usr/bin/node",
    "workspace": "/<abs>/.sandbox-runtime/den-router-coding-workspace"
  }
}
```

## Coding Suite Test Discrimination

The 8 coding scenarios vary widely in difficulty against cloud models. Recommended selection for cost-efficient cloud runs:

**Skip (too easy / low signal):**
- `coding.roman-numerals` — subtractive notation fix. Near-universal pass.
- `coding.export-report` — small formatting/counts fix. Low discrimination.

**Keep (moderate to hard):**
- `coding.expression-evaluator` — Pratt parser, right-assoc `^`, floor division, implicit multiplication, functions/constants.
- `coding.tree-prune` — promotion semantics, cascading removal, order preservation, immutability.
- `coding.kth-selection` — O(n) selection with no mutation and no O(n) auxiliary storage.
- `coding.weighted-split` — deterministic cents distribution.
- `coding.retry-policy` — parser with repeat expansion and strict malformed-input rejection.
- `coding.cache-key` — semantic stability fix. Borderline; keep unless short on time.

## Coding Suite Runner Constraints

The coding suite is **not** a generic chat benchmark. It requires candidates that can execute code against a disposable workspace. The runner enforces this through `CodingCandidateRunner` and `CodingAgentRunner`:

- **Accepted:** `cli_command: "coding-scripted"` (scripted/deterministic) or `kind: "CodingAgent"` (real CLI like pi)
- **Rejected (SKIP):** plain OpenAI chat candidates (`kind: "OpenAiModel"`, `cli_command: "mcp-openai-tool-use"`) — `OpenAiChatRunner` cannot satisfy the coding scorer’s workspace/test execution contract

**Practical implication:** you cannot run `suites/coding/*` against den-router chat candidates directly. Options:
1. Add pi-style `CodingAgent` candidates with a pi extension that routes through den-router (same pattern as Lemonade local runs).
2. Use pi with `--provider den-router --model <name>` and a custom `models.json` pointing at `127.0.0.1:18082/v1`.
3. Build a dedicated coding-runner wrapper for chat models (more work, not yet implemented).

## Runner Flags

- `--skip-scenario <id>` — exclude one scenario from the run (repeatable).
- `--exclude-scenario <id>` — alias for `--skip-scenario`.
- `--suite`, `--scenario`, `--candidate` — inclusion filters as before.
- Skip filters are applied after suite/scenario inclusion, so `--suite coding --skip-scenario coding.roman-numerals` works as expected.

## Coding Suite Test Discrimination

The 8 coding scenarios vary widely in difficulty against cloud models. Recommended selection for cost-efficient cloud runs:

**Skip (too easy / low signal):**
- `coding.roman-numerals` — subtractive notation fix. Near-universal pass.
- `coding.export-report` — small formatting/counts fix. Low discrimination.

**Keep (moderate to hard):**
- `coding.expression-evaluator` — Pratt parser, right-assoc `^`, floor division, implicit multiplication, functions/constants.
- `coding.tree-prune` — promotion semantics, cascading removal, order preservation, immutability.
- `coding.kth-selection` — O(n) selection with no mutation and no O(n) auxiliary storage.
- `coding.weighted-split` — deterministic cents distribution.
- `coding.retry-policy` — parser with repeat expansion and strict malformed-input rejection.
- `coding.cache-key` — semantic stability fix. Borderline; keep unless short on time.

## Fuzzy / Autonomy / Grounding Suites — Candidate Routing

`autonomy-calibration` and `evidence-grounding` are NOT MCP suites. They require
`OpenAiFuzzyAgentRunner`, which handles plain `OpenAiModel` candidates that do
**not** have `cli_command: mcp-openai-tool-use`.

**Critical routing rule:** if a candidate has `cli_command: mcp-openai-tool-use`
or `config.runner: mcp-openai-tool-use`, it will be handled by
`OpenAiMcpToolUseRunner`, which throws when given non-MCP scenarios.

Always create separate `-fuzzy` suffixed candidates for these suites:
```json
{
  "id": "den-router-<model>-fuzzy",
  "kind": "OpenAiModel",
  "model": "<model-id>",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "config": {"temperature": 0.2, "max_tokens": 4096}
}
```

See `references/fuzzy-agent-scorer-and-chat-candidates.md` for the full
scorer contract, observed false-negative pattern, and in-progress fix path.

## pi-crew Worker Tests: Script-Based Matrix, Not Runner-Based

When a task asks for a pi-crew worker model/profile suitability matrix (e.g. task #2283), build it as a **standalone script** under `scripts/` in the GoblinBench repo, not as a `CodingAgentRunner` integration test or a .NET runner scenario. Reasons:

- These tests must call Den MCP tools directly (`create_task`, `lease_worker`, `get_worker_run_status`, `get_latest_worker_completion`, `list_pool_members`, `cleanup_worker_run`) to drive the worker lifecycle.
- The `den-router` model list is supplied externally, not discovered from pi-crew config.
- Results are relational/now-oriented comparisons, not historical artifacts.
- pi-crew worker runs may hit long timeouts, malformed packets, or schema drift; a script can iterate quickly, switch to manual/import mode, and capture failure categories without rebuilding the .NET runner.

Preferred shape:
- Script under `scripts/pi-crew-worker-matrix/` or similar.
- Creates one Den task per matrix cell, tags it with `goblinbench`, `model:<name>`, `profile:<name>`, `artifact:<kind>`, `role:<role>`, plus a campaign ID.
- Treats the tested model as the model configured on the leased worker profile. **Do not fake a den-router model × worker cross-product**: `lease_worker` selects a configured pool member/profile, not a per-assignment model override. Only vary models when model-specific worker profiles/members are actually installed or supplied via an explicit matrix matching current config.
- Records substrate_success vs deliverable_success separately.
- Writes `runs/pi-crew-matrix-<id>/matrix.json` + flat `matrix.md`.
- Supports `--manual` import mode for fallback when live leasing is unstable.

Keep the older bwrap/CodingAgentRunner pattern for **coding-agent CLI tests** only (pi as a subprocess against a fixture workspace). Do not conflate the two test shapes.

## Planner Misroute / Task-Ambiguity Pitfall

If a task description or planner assignment looks like it targets the wrong project (e.g. a GoblinBench-scoped test landed in pi-crew), **stop and ask for clarification before building**. Spending tool calls exploring the wrong repo/CLI/tooling is a strong signal that the task scope is misrouted. This is especially important when:
- The user explicitly warns that the planner put the task in the wrong project.
- Local repo structure contradicts the task description.
- Required CLI/tooling (`den`, `pi`, etc.) is missing from the environment.

Do not guess or silently switch contexts; confirm the deliverable and its repo first.

## Den Task Access in Restricted Environments

The `den` CLI is not guaranteed to be on PATH in all Hermes/agent environments. When reading or writing Den task state, prefer MCP tools (`mcp_den_get_task`, `mcp_den_list_tasks`, `mcp_den_send_message`, etc.) over shelling out to a `den` binary. If MCP tool access is also unavailable, say so and ask the user for direction rather than retrying shell commands.

## Runner Architecture: .NET Harness and ScriptBridge

The goblinbench runner lives at `src/GoblinBench.Runner/Program.cs` — a .NET 10
console app with hardcoded runner and scorer registration. This is the harness
that all GoblinBench evaluations run through.

### Component layout

```
src/
├── GoblinBench.Core/       Interfaces: ICandidateRunner, IScorer, types
├── GoblinBench.Runner/     Program.cs — discover, dispatch, write results
├── GoblinBench.Candidates/ Runner implementations (14 runners)
├── GoblinBench.Scorers/    Scorer implementations (14 scorers)
```

### Runner registration (hardcoded)

`Program.cs` lines 126–143 register all `ICandidateRunner` instances in an
ordered list. The first runner whose `CanHandle(candidate)` returns true wins.
Order matters — `ScriptedCandidateRunner` must come before `NoOpCandidateRunner`
because NoOp matches any `Kind=Unknown` candidate.

```csharp
var runners = new List<ICandidateRunner>
{
    new ScriptedCandidateRunner(),    // cli_command-based matching
    new FakeMcpCandidateRunner(),
    ...
    new CodingAgentRunner(),          // kind: "CodingAgent" — pi inside bwrap
    new CodingCandidateRunner(),      // cli_command: "coding-scripted"
    ...
    new NoOpCandidateRunner(),        // fallback — matches any Kind=Unknown
};
```

### Scorer registration (hardcoded)

`Program.cs` lines 145–161 register all `IScorer` instances by `Id` string.
Scorers are filtered at runtime: only those named in `scenario.Scoring.Scorers`
are invoked. If the scenario declares no scorers, *all* registered scorers run.

```csharp
var scorers = new List<IScorer>
{
    new NoOpScorer(),                // "noop"
    new CodingTestScorer(),          // "coding-tests" — dotnet-hardcoded
    new CommandScorer(),             // "command" — runs arbitrary shell command
    new LatencyScorer(),             // "latency"
    ...
};
```

### Scorer dispatch

For each (scenario × candidate), the runner:
1. Picks the matching runner via `CanHandle()`
2. Calls `runner.RunAsync(scenario, candidate, context)`
3. Filters scorers to those declared in `scenario.Scoring.Scorers`
4. Calls `scorer.ScoreAsync(...)` for each, appending to `candidateResult.Scores`
5. Writes `run.json` with full result tree

### Python scoring pipeline (post-processing)

Introduced June 2026. A Python pipeline (`scripts/gb-score.py`) runs as a **post-processing step** after the .NET runner finishes. Wired into `Program.cs` via `Process.Start` after `run.json` is written.

**Architecture:**
  - `gb-score.py` reads `run.json`, discovers scenario JSONs from `suites/`
  - Dispatches to scorer scripts in `scripts/scorers/<scorer_id>.py`
  - Each scorer script receives `--fixture-dir <path>`, returns ScoreResult JSON on stdout
  - Pipeline writes updated `run.json` back (scores merged)

**Language-agnostic test runner** (`coding-tests.py`):
  - `pyproject.toml` / `pytest.ini` → pytest
  - `*.csproj` → dotnet test (restore/build/test)
  - `Cargo.toml` → cargo test
  - `package.json` + jest/vitest/mocha → npm test

**Score replacement:** The Python pipeline replaces .NET `coding-tests` scores when a Python script exists for the same ID (detected by `scoring_kind != "script"`), making the Python runner canonical for non-C# fixtures.

**Structure-metrics scorer** (`structure-metrics.py`):
  - AST analysis of implementation files (not tests)
  - Emits: LOC/fn distribution (min/max/mean/p95), type-annotation depth, docstring coverage, test-to-source ratio, try/except count, import count
  - Non-binary — always passes with score=1.0, the detail carries the signal

**Interface-seeded style probes** — A new scenario class for measuring training-data gravity:
  - Fix interfaces/types + test suite (same across languages)
  - Provide stub implementation files with function signatures only
  - Agent fills bodies — structure metrics capture gravity signal
  - Avoids "too trivial → no style / too sprawling → incomparable" problem
  - Example: `fixtures/coding/batch-ingestion/` (Python, 5 files, 49 tests)

### The dotnet hardcoding bottleneck (CodingTestScorer)

`CodingTestScorer` (Id: `"coding-tests"`) is the only scorer for coding
scenarios. It is fully hardcoded for .NET:
- Build: runs `dotnet restore --force` then `dotnet build -v quiet`
- Test: runs `dotnet test --no-build --filter <filter>` then parses dotnet's
  summary line format (`"Passed: X, Failed: Y, Total: Z"`)
- Scan: looks for TODO/FIXME/HACK markers only in `*.cs` files
- No way to switch to pytest, cargo test, or any other test framework

### Python Post-Processing Scoring Pipeline (Option 2 — Implemented)

**Supersedes the proposed .NET ScriptScorer bridge.** Instead of adding a new
.NET class, the scoring pipeline runs entirely in Python as a post-processing
step after the .NET runner finishes.

**Architecture:**

```
.NET Runner → run.json (candidate results, fixture_dir, raw outputs)
                          │
                          ▼
    python3 scripts/gb-score.py <run-dir> [--verbose]
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
    scorers/        scorers/        scorers/
    coding-tests.py  metrics/*.py   <other>.py
```

**Key properties:**
- **Language-agnostic** — adding a new language = add fixture + test config; no .NET changes
- **No .NET recompilation** — new scorers are Python scripts dropped in `scripts/scorers/`
- **Idempotent** — re-running skips already-scored entries
- **Composable** — .NET scorers (latency, vision, MCP, etc.) still run via the harness;
  the Python pipeline only handles scorer IDs with a matching `scripts/scorers/<id>.py`

**Scorer contract:**

Each script in `scripts/scorers/` accepts:
```
--fixture-dir <path>       # Required: the implementation directory
--artifact-dir <path>      # Optional: where to write detail artifacts
--threshold <float>        # Optional: pass/fail threshold
--params <json>            # Optional: scenario-specific parameters
```

Emits one JSON object on stdout:
```json
{
  "scorer_id": "coding-tests",
  "scorer_name": "Coding Test Scorer",
  "scoring_kind": "script",
  "success": true,
  "score": 1.0,
  "passed": true,
  "human_summary": "PASS",
  "explanation": "pytest: 49/49 passed, 0 failed",
  "detail": {"language": "python", "passed": 49, "total": 49}
}
```

**Current scorer scripts:**

| Script | Detects | Runs | Scorer ID |
|---|---|---|---|
| `scorers/coding-tests.py` | `pyproject.toml` -> pytest, `*.csproj` -> dotnet, `Cargo.toml` -> cargo, `package.json` -> npm test | See auto-detection | `coding-tests` |
| `scorers/structure-metrics.py` | Wraps `scripts/structure-metrics.py`, AST analysis, emits LOC/fn, type-depth, docstring %, test:source, try/except | Python fixture dir | `structure-metrics` |

**Adding a new language:**
1. The auto-detector in `coding-tests.py` likely already handles it (covers Python, .NET, Rust, TypeScript)
2. If not, add a detection check + runner function in `coding-tests.py`
3. Or write a new `scorers/<custom-id>.py` for framework-specific scoring
4. Reference the scorer ID in the scenario JSON's `scoring.scorers` array

**Usage:**

```bash
# After a .NET run completes:
python3 scripts/gb-score.py runs/run-20260619-123456-abcd1234/ --verbose

# Standalone scorer test:
python3 scripts/scorers/coding-tests.py --fixture-dir fixtures/coding/batch-ingestion/
```

See `references/python-scoring-pipeline.md` for the full architecture, scorer
contract, adding new languages, and verified behaviour.

### Adding a new runner type

1. Create a new C# class in `GoblinBench.Candidates/` implementing `ICandidateRunner`
2. Add it to the runners list in `Program.cs` — pay attention to ordering
   (more specific matchers first)
3. Define the candidate entry in `candidates.json` with fields that make
   `CanHandle()` match

### Adding a new scorer type

1. Create a new C# class in `GoblinBench.Scorers/` implementing `IScorer`
   (`string Id`, `string Name`, `Task<ScoreResult> ScoreAsync(...)`)
2. Register it in `Program.cs` scorers list
3. Reference it by `Id` in scenario JSON's `scoring.scorers` array
4. Provide parameter config under `scoring.parameters.<id>`

### Mode B (Tool-driven) runner design

Task #2573 requires a runner that gives models tool access (file read, grep, ls)
to explore a codebase independently, rather than receiving a static packet.
This is a fundamentally different shape from any existing runner:

- Not a `CodingAgent` — no bwrap sandbox, no fixture copy
- Not an `OpenAiMcpToolUseRunner` — the tools are filesystem tools, not MCP tools
- Needs: tool call budget enforcement, exploration metrics (files touched,
  wasted reads, found-issue-per-read efficiency)
- Output format must match Mode A's `findings.json` + `analysis.md` for the
  shared judge pipeline

Recommended approach: a new `CodebaseAnalysisToolRunner` in
`GoblinBench.Candidates/` that uses an OpenAI chat loop with custom tool
definitions (read, ls, grep), enforces a tool budget, and produces structured
findings output. Reuses `fixtures/codebase-analysis/den-core-v1/`,
`gold-ledger.json`, and the Mode A judge/scoring pipeline.

## Subprocess Sandbox Pattern: Friction, Not Fortress

The recurring sandbox need is accidental-damage prevention: a coding agent CLI receives a fixture and may run bad shell commands. Reads and network are often acceptable; writes are what matter.

Standard shape:

1. Resolve the agent binary and dependencies to absolute paths; chase symlinks and log a SHA-256 of entry scripts.
2. Snapshot the workspace before the run.
3. Build a `bwrap` profile with `--unshare-all`, `--die-with-parent`, usually `--share-net`, `--ro-bind / /`, tmpfs scratch directories, `--dev /dev`, a writable bind of the disposable workspace under `/tmp/agent-workspace`, `--clearenv`, explicit env vars, `--chdir`, then the inner command.
4. Capture stdout, stderr, exit code, wall-clock duration, trace events, and a post-run workspace snapshot/diff.
5. Run the scorer against the modified workspace and preserve `agent.patch` even when the agent exits nonzero or times out.

Validate the sandbox with fake agents before real models: one fake writes inside the workspace and exits 0; a negative fake attempts writes outside the workspace and asserts no host file was created.

## Sandbox Gotchas

- `--ro-bind /usr /usr` can break ELF dynamic linker resolution; prefer `--ro-bind / /`.
- Bind destinations need writable parents; mount workspace under a tmpfs parent such as `/tmp/agent-workspace`.
- Resolve symlinked inner commands with `readlink -f` / equivalent.
- Guard optional `--ro-bind` source paths because bwrap refuses missing sources.
- Put agent `HOME`, caches, and CLI home under the disposable workspace unless you intentionally bind config read-only.
- Network is opt-in with `--share-net`; most model/API/restore runs need it.
- A fresh `--dev /dev` is required for runtimes that open `/dev/null` or spawn subprocesses with ignored stdio.
- Mock LLM servers used with streaming clients must return SSE (`Content-Type: text/event-stream`, `data: ...\n\n`, final `data: [DONE]`).
- Many agent CLIs do not accept `--base-url`; configure custom OpenAI-compatible providers via their `models.json`/config directory and verify with the CLI's list-models command.

## Reusable References and Files

Evaluation references:

- `references/streamable-http-den-mcp-catalog-refresh.md` — direct streamable HTTP `initialize` + `tools/list` refresh pattern for pinning live Den MCP tool catalogs without expanding Hermes tool context.
- `references/agent-lab-to-goblinbench-port.md` — agent-lab → GoblinBench porting pattern.
- `references/roleplay-heat-boundary-matrix-2026-07-07.md` — roleplay/adult-romance boundary matrix pattern: direct PG-13→soft-R→NC-17 ladder, deterministic `roleplay-heat-boundary` scorer, classification-only reporting, den-router/Lemonade candidate config notes, and long-thinker smoke-probe token-budget gotchas.
- `references/roleplay-prose-instruction-matrix-2026-07-08.md` — SFW roleplay prose + strict no-user-control matrix pattern: provider split runs, Grok judge command shape, public headline-summary structure, observed prose-vs-agency separation, and duplicate artifact basename publishing gotcha.
- `references/requested-regression-matrix-2026-07-09.md` — rerun pattern for broad tool-calling, deceptive/adversarial tool-use, hallucination/groundedness, and codebase-analysis matrices after old pre-DB artifacts are missing: canonical store audit, category→suite mapping, separate MCP/session/fuzzy candidate files, den-router model smoke probes, `glm-5.2`/`kimi-code` parameter gotchas, and reporting commands.
- `references/pi-lemonade-json-mode.md` — local pi/Lemonade candidate pattern (coding-agent runs with pi extension).
- `references/lemonade-direct-api-local-model-comparison.md` — Lemonade Server direct OpenAI-compatible API as GoblinBench candidates (no pi wrapper). Covers candidate config layout, quant-level comparison pairs, cold-start timing, smoke-test pattern, and `builtin.*` naming convention for same-model different-quant runs.
- `references/openai-mcp-tool-runner-and-local-model-comparison.md` — OpenAI-compatible fake-MCP runner loop and local model comparison.
- `references/environment-realized-agent-evaluation.md` — two-lane model-core vs environment-realized methodology, generic app-server/worker adapter contract, workspace/provenance/cost capture, and rollout pattern.
- `references/den-router-candidate-comparison.md` — den-router (`http://127.0.0.1:18082/v1`) candidate config layout, `/v1/models` vs routability smoke probe, reasoning-model token budgeting, model-specific parameter constraints (kimi `temperature: 1.0`), SSE-whitespace response quirk (stepfun/hy3), A/B hinted-suite run pattern, reasoning effort config support and experimental findings, SOTA model behavior on ambiguity suite, intermittent upstream failure recovery pattern, and multi-round A/B merge analysis.
- `references/den-mcp-ambiguity-ab-comparison-2026-06-09.md` — 13-model A/B comparison results (baseline vs hinted) across 3 rounds, per-scenario difficulty ranking, reasoning-vs-standard model hint sensitivity, and pitfall log (kimi temp, backend outages, report suite filter, nex-n2-pro response parsing).
- `references/den-mcp-ambiguity-ab-comparison-2026-06-10.md` — 6-model A/B comparison (glm, kimi, mimo, stepfun, hy3, minimax) after router state change (nemotron dead, minimax rate-limited). GLM hint-sensitivity reversal, curl smoke-probe quoting pitfall, minimax 429 silent-failure pattern.
- `references/den-mcp-ambiguity-ab-comparison-2026-06-12.md` — requested local-router A/B rerun after regenerating baseline + hinted suites. `glm` and `minimax` reached 5/6 hinted; `nemotron` and `hy3` smoke-probed 404 and were skipped.
- `references/mcp-hard-suite-local-comparison-2026-06-06.md` — concrete `mcp-tools-hard` comparison recipe and interpretation.
- `references/mcp-tools-suite-shape-and-bypass-pattern.md` — `mcp-tools` (not -hard) suite shape, scenario catalog, and the reusable bypass-resistance design (fake `http_raw_fetch` + `allow_bypass` + `scripted_bypass_attempts` array).
- `references/orchestrator-suite-sanity-vs-discrimination.md` — interpreting perfect synthetic orchestrator-suite scores, including the `scripted_response` prompt-leak contamination pattern.
- `references/coding-suite-runner-routing.md` — coding suite runner selection order, why den-router chat candidates are silently skipped, and workarounds (pi extension, den-router provider config).
- `references/pi-den-router-coding-candidate.md` — den-router-backed pi coding-agent candidate pattern: workspace layout, candidate config shape, smoke-test recipe, and verified model list.
- `references/pi-glm52-dotnet-supervision-investigation-2026-06-20.md` — GLM52/pi investigation showing exact `bwrap_argv` passed from a Python parent while the same candidate failed under `.NET CodingAgentRunner`; use as the pattern for separating model/provider/bwrap failures from parent-process supervision failures.
- `references/python-runner-glm52-validation-2026-06-20.md` — follow-up validation of the drop-in Python runner: `scripts/gb-run.py` successfully ran the GLM52 maintainability probe and exposed the `start_new_session=True` bwrap launch pitfall in the Python port.
- `references/goblinbench-python-only-runner-cleanup-2026-06-21.md` — Python-only runner cleanup pattern: remove verified-dead .NET runner/tests and old C# coding fixtures, patch root detection/docs/scorer branches, add pytest coverage for store/report safety, and keep benchmark-subject C# fixtures distinct from runner legacy.
- `references/pi-crew-worker-matrix-script-pattern.md` — standalone script pattern for pi-crew worker model/profile suitability matrices: Den MCP transport, matrix cell shape, timeout guidance, and manual/import mode.
- `references/goblinbench-results-cli.md` — SQLite-backed `scripts/gb-results.py` query CLI for cross-run/model/suite comparisons, run-set filtering, failure-category summaries, and low-token agent drilldowns.
- `references/kimi-code-den-router-benchmark-2026-06-13.md` — `kimi-code`/upstream `kimi-k2.7-code` den-router benchmark notes: temperature=1.0 requirement, candidate shapes by suite family, 429-targeted retry/final-run-set pattern, and suite results.
- `references/codebase-analysis-benchmark-2026-06-16.md` — Codebase Analysis Mode A benchmark (fixture design, gold ledger, decoys, packet generation, scoring rubric, runner). Full-source results at `goblinbench/codebase-analysis-mode-a-benchmark-3-full-source-5-models` (winner: minimax 83%). Also see prior runs at `...-benchmark-2` (leaky-packet comparison) and `...-benchmark-1` (deprecated leaky-packet run).
- `references/style-probe-interface-seeded-design.md` — Methodology for interface-seeded style probes (training-data gravity measurement): the observability problem, interface-seeded approach, design principles, metric set rationale, and the Batch Ingestion Pipeline reference implementation (Python, `fixtures/coding/batch-ingestion/`). For porting to TypeScript/Rust or designing new probes.
- `references/batch-ingestion-language-gravity-2026-06-19.md` — Session reference for the Python→TypeScript batch-ingestion port, first same-model Python-vs-TS comparison, TS/Vitest fixture shape, generated-artifact cleanup gotchas, and lightweight TS structure-metrics approach.

Sandbox references and reusable files:

- `references/bwrap-gotchas.md` — reproduction recipes for bwrap and sandbox failures.
- `scripts/verify-bwrap.sh` — host smoke test for bwrap/user namespaces/basic profile shape.
- `scripts/mock-openai-compat-server.js` — deterministic streaming SSE OpenAI-compatible mock for agent harness tests.
- `scripts/structure-metrics.py` — standalone AST-based structural analysis scorer for style probes. Analyzes Python implementation directories and emits file/function/metrics JSON. Run: `python3 scripts/structure-metrics.py <dir> [--output results.json]`.
- `scripts/gb-score.py` — Python post-processing scoring pipeline orchestrator. Reads a .NET run.json, discovers scenario JSONs, dispatches to `scripts/scorers/<id>.py`, writes updated scores. Run: `python3 scripts/gb-score.py <run-dir> [--verbose]`.
- `scripts/scorers/coding-tests.py` — Language-detecting test runner for the scoring pipeline. Auto-detects fixture language (Python/pytest, .NET/dotnet, Rust/cargo, TS/npm test) and runs the appropriate test command. Accepts `--fixture-dir`, `--artifact-dir`, `--threshold`, `--params`. Invoked automatically by `gb-score.py`.
- `scripts/scorers/structure-metrics.py` — Structure-metrics scorer wrapper. Wraps `scripts/structure-metrics.py` and emits ScoreResult JSON for the pipeline. Invoked automatically by `gb-score.py`.
- `templates/pi-models.json` — known-good custom provider config for pi/local OpenAI-compatible endpoints.
- `templates/pi-coding-agent-candidate.json` — known-good pi + bwrap candidate entry.

## Verification Checklist

- [ ] Deterministic candidate passes scenario discovery/scoring before real model runs.
- [ ] Fixture copy/isolation and scenario-scoped artifacts verified.
- [ ] Runner status, model status, scoring status, and patch artifacts reported separately.
- [ ] Sandbox profile tests assert argv order and dangerous invalid profiles are rejected.
- [ ] Real bwrap fake-agent positive and escape-negative tests pass on the current host.
- [ ] Mock servers return streaming SSE and terminate after tool results.
- [ ] Final reports expose failure categories/task-shape tags, not just totals.
- [ ] For cloud-routed candidates, `/v1/chat/completions` smoke probe succeeds on each model id before scheduling a real run.
- [ ] **Task sizing check:** the scenario is large enough for observable variation but constrained enough for cross-run comparison. Single-file bug fixes (zero style room) and open-ended "build an app" (incomparable architecture) are both antipatterns unless that's the explicit measurement target.
