# Python runner (`scripts/gb-run.py`)

A drop-in Python port of the .NET runner (`src/GoblinBench.Runner`), built to
replace the execution layer while leaving every downstream tool untouched.

## Why

The .NET runner had a class of crash-with-no-trace failures under specific
conditions that did not reproduce through a Python shim against the same
scenarios. That asymmetry pointed at a runtime/GC/native-interop/SSE-socket
edge rather than a logic bug, so the fix is to move the execution layer to a
runtime that does not exhibit it.

The port is low-risk because the bench already had a clean seam: `gb-score.py`,
`gb-results.py`, and the `scripts/scorers/*.py` plugins consume the runner's
output through a **stable on-disk contract** (`runs/<run-id>/run.json` +
per-candidate `output.json` / `trace.jsonl` / `scores.json`). Producing that
same tree from Python makes the producer language irrelevant to everything
downstream.

## Status

### Milestone 1 — minimum test runner (DONE)

- Domain models, scenario discovery, run context (port of `GoblinBench.Core`).
- Main loop with the same CLI filters (`--suite`, `--scenario`, `--candidate`,
  `--candidates`, `--skip-scenario`/`--exclude-scenario`) and `gb-score.py`
  handoff as `Program.cs`.
- Runners: **NoOp**, **Scripted** (green-path / deterministic smoke).
- Scorers: **Latency**, **SchemaCompliance** (deterministic).
- Validated by artifact-diff against historical .NET runs: identical key sets
  at every level (RunResult / PerScenarioResult / CandidateResult /
  ModelIdentity / ScoreResult), correct deterministic scores (independently
  hand-verified), and `gb-results.py import` indexes Python runs alongside
  .NET runs with zero changes.

### Milestone 2 — real workload (DONE)

- `CodingAgentRunner` + `BwrapProfile` (port of `CodingAgentRunner.cs` /
  `Sandbox/BwrapProfile.cs`) — the bwrap-sandboxed `pi` hot path. This is where
  the cursed behavior bit, so this is the milestone that retires .NET for real
  work. Validated end-to-end: sandbox launches, the writable `/work` bind works,
  `message_update` stdout noise is filtered, file edits are snapshotted/diffed,
  `output["fixture_dir"]` is set, and the test scorer runs against it.
- `CodingCandidateRunner` (deterministic `coding-scripted` path — applies
  `correct_patch.json`). Validated end-to-end against `coding.retry-policy`:
  patch applied → `fixture_dir` set → `gb-score.py` runs `coding-tests.py` →
  `dotnet test` → 4/4 passed → score merged.
- `OpenAiChatRunner` (covers the 15 plain-chat `OpenAiModel` candidates).
  Stdlib-only (`urllib`, zero deps). Validated live against the den-router
  endpoint and structurally diffed against a historical .NET run of the same
  candidate+scenario — identical `output` / `model_identity` / key sets.

### Scoring note (no scorer ported into the package)

The authoritative `coding-tests` scorer is already `scripts/scorers/coding-tests.py`
(multilingual: python/dotnet/go/rust/typescript), invoked by `gb-score.py` via
`output["fixture_dir"]`. The C# `CodingTestScorer` is vestigial (.NET-only).
So Milestone 2 adds **no scorer** to the package — the runners just set
`output["fixture_dir"]` and the existing Python scorer handles the rest.

### Milestone 3 — coverage (DONE)

Ported the four specialized `OpenAiModel` runners + the five scorers they depend
on. These cover the remaining candidate/scenario combinations the bench
actually exercises:

- `OpenAiMcpToolUseRunner` (port of `OpenAiMcpToolUseRunner.cs`) — the bulk
  path: multi-round tool-call loop against an OpenAI endpoint, mapping
  scenario `fake_mcp.tools` to the OpenAI tool schema and executing requested
  calls against canned `scripted_tool_calls` results. 38 candidates.
- `OpenAiFuzzyAgentRunner` (port of `OpenAiFuzzyAgentRunner.cs`) — asks the
  model for a structured decision packet (`response_format=json_object`) and
  recovers it from prose/fences.
- `OpenAiMcpSessionRunner` (port of `OpenAiMcpSessionRunner.cs`) — multi-turn
tool-call loop preserving chat history across `input.turns[]`.
- `VisionCandidateRunner` (port of `VisionCandidateRunner.cs`) — multimodal:
  encodes `input.image_paths` as base64 data URLs.

Scorers ported as in-process Python scorers (M1 pattern):
- `McpToolUseScorer` (28 scenarios) — expected calls, argument grounding,
  forbidden tools/bypasses, optional-parameter stuffing, error recovery,
  clarification, artifact markers. Large detail surface, field-for-field parity
  with the C# output.
- `OrchestratorDecisionScorer` (8), `VisionCorrectnessScorer` (7),
  `FuzzyAgentBehaviorScorer` (6), `McpSessionTrajectoryScorer` (1).

All five scorer logics independently hand-verified. All four runners validated
live against the den-router endpoint and structurally diffed against historical
.NET runs — output key sets identical.

### Shared OpenAI helpers (`scripts/gb/runners/_openai.py`)

The four specialized runners + the existing chat runner all carry near-identical
copies of HTTP plumbing, API-key resolution, config extraction, secret redaction,
message/tool parsing, and JSON extraction (5× in C#). Centralized into one
stdlib-only helper module so the ports stay drift-free. No `requests`/`httpx`
dependency — the runner stays zero-dependency (stdlib `urllib` only).

### Not ported (vestigial — no candidates use them)

`HermesProfileRunner`, `ServiceEndpointRunner`, `ExternalCliRunner`, and
`ElectronCandidateRunner` have **zero candidates** in `candidates.json` — they're
dead code in both .NET and Python. Skipped intentionally. (The `ElectronFlowScorer`
and `CodingTestScorer` C# scorers are similarly unused; `coding-tests` is already
the multilingual Python plugin under `scripts/scorers/`.)

### Coverage

**All 72 candidates now claimed (100%)** across 9 runners. All scenario-declared
scorers (except the Python-plugin-only `structure-metrics`/`maintainability-metrics`,
handled by `gb-score.py`) are now in-process Python scorers. The .NET runner is
no longer needed for any real workload.

### Dropped (not porting)

- `ReportServer` / `ReportGenerator` (~1.6k LoC) — the live viewer is no longer
  used; dead code, intentionally left in .NET for now and not reproduced.
- Den post-to-SSE client (lived in the dead report path).

## Usage

```bash
# same flags as the .NET CLI
python3 scripts/gb-run.py
python3 scripts/gb-run.py --suite orchestrator --candidate scripted-deterministic
python3 scripts/gb-run.py --scenario orchestrator.malformed-completion-packet
python3 scripts/gb-run.py --candidates path/to/candidates.json
```

Produces `runs/run-<timestamp>-<8hex>/` with the same layout as the .NET runner
and then hands off to `scripts/gb-score.py` (unchanged).

## Layout

```
scripts/
  gb-run.py                 entrypoint + main loop (port of Program.cs)
  gb/
    models.py               dataclasses + CandidateKind enum (GoblinBench.Core)
    context.py              RunContext path helpers
    discovery.py            scenario discovery + filters
    registry.py             runner/scorer registries + first-match dispatch
    serialize.py            JSON contract matching System.Text.Json output
    fsutil.py               fixture copy / snapshot / unified-diff helpers
    sandbox/
      bwrap.py              BwrapProfile — argv builder + Validate() (BwrapProfile.cs)
    runners/
      base.py               CandidateRunner protocol
      _openai.py            shared OpenAI HTTP + parsing helpers (extracted from 5 C# runners)
      noop.py               NoOpCandidateRunner
      scripted.py           ScriptedCandidateRunner
      coding_scripted.py    CodingCandidateRunner (deterministic correct_patch.json)
      coding_agent.py       CodingAgentRunner (bwrap-sandboxed pi — the hot path)
      openai_chat.py        OpenAiChatRunner (OpenAI-compatible /chat/completions)
      mcp_tool_use.py       OpenAiMcpToolUseRunner (multi-round tool calls)
      fuzzy_agent.py        OpenAiFuzzyAgentRunner (decision packet)
      mcp_session.py        OpenAiMcpSessionRunner (multi-turn)
      vision.py             VisionCandidateRunner (multimodal images)
    scorers/
      base.py               Scorer protocol
      latency.py            LatencyScorer
      schema_compliance.py  SchemaComplianceScorer
      orchestrator_decision.py
      mcp_tool_use.py
      vision_correctness.py
      fuzzy_agent_behavior.py
      mcp_session_trajectory.py
  scorers/                  (existing) gb-score.py post-processing plugins — untouched
```

New ports append to `gb/registry.default_runners()` /
`default_scorers()`.

## Validation methodology

The acceptance bar is **artifact-contract equivalence**, not byte-equality
(timestamps and latency durations legitimately drift run-to-run):

1. Run the Python runner on a deterministic scenario also exercised by .NET.
2. Compare key sets at every JSON level — must be identical.
3. For deterministic scorers, scores / passed / success must match exactly;
   for latency, the formula and shape must match (duration is allowed to vary).
4. Independently hand-compute expected scorer results where no .NET baseline
   exists (proves *correctness*, not just sameness).
5. `gb-results.py import` must index the run with zero changes.

## Note: `trace.jsonl` format

The .NET runner produced malformed `trace.jsonl` files: one compact event
written by the candidate runner followed by **indented, multi-line** JSON
objects written by the main loop (the two writers used different
`JsonSerializerOptions`). The result was not valid JSONL. Nothing downstream
reads `trace.jsonl`, so this was a latent cosmetic bug. The Python runner emits
clean compact JSONL (one object per line) — strictly more correct and more
useful as a debug artifact. This is the kind of "haunted alley" the port
retires for free.
