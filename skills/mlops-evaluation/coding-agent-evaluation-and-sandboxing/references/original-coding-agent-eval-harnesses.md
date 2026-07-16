---
name: coding-agent-eval-harnesses
description: Build, port, debug, and verify coding-agent benchmark/evaluation harnesses with fixtures, visible/strict tests, sandboxed runners, and reproducible result artifacts.
version: 1.0.0
author: GoblinOverseer
license: MIT
metadata:
  hermes:
    tags: [coding-agents, evaluation, benchmarks, test-harnesses, fixtures, goblinbench]
    related_skills: [test-driven-development, systematic-debugging, den-mcp]
---

# Coding-Agent Eval Harnesses

Use this skill when working on benchmark harnesses for coding agents: importing legacy coding tasks, designing fixtures, wiring candidate runners, scoring visible/strict tests, debugging artifact capture, or validating end-to-end model runs.

## Core workflow

1. **Start from durable task state.** If this is Den-tracked work, create/update the Den task first and keep progress notes there. Treat repo notes as secondary unless Den points at them.
2. **Preserve upstream task fidelity.** When porting benchmark tasks, keep the original prompt/ticket text, source URL/commit, fixture provenance, and any normalization notes in the scenario metadata.
3. **Port fixtures as runnable workspaces.** Each scenario should have a self-contained fixture directory with starter source, visible tests, strict tests, project/build file, and optional known-good patch.
4. **Verify before launching real models.** Use a deterministic/no-op/scripted candidate first. Confirm fixture builds, test filters select the intended visible/strict tests, and baseline scores match the expected broken-starter shape.
5. **Then run real candidates.** Only after deterministic harness checks are clean should you spend model time on pi/Codex/Claude/etc.
6. **Capture interpretable results.** Preserve model/provider, candidate config, prompt/scenario version, harness version, command, environment, pass counts, score, exit status, and artifact paths.
7. **Make comparison reports task-shape aware.** When reports get dense, add failure categories and task-shape tags (tool forest, schema grounding, refusal boundary, multi-turn memory, etc.) plus a static HTML explorer with filters/sort/drilldowns. The goal is model-fit discovery for specific task shapes, not decorative dashboards.
8. **Separate runner health from scoring health.** A killed/timed-out agent can leave a partial patch that scores nonzero. Report process status and test-score status separately, and avoid treating partial-run scores as clean model-quality metrics.

## Fixture/scenario design checklist

- Fixture source is copied into a per-run workspace; the original fixture remains immutable.
- Visible and strict tests are separately selectable by stable filters such as namespace or test traits.
- The scoring config names the test project explicitly instead of relying on incidental first-`*.csproj` discovery when multiple projects may exist.
- Marker scans target the source directory that candidates are expected to edit.
- Threshold semantics match benchmark intent. For coding maintenance tasks, prefer full pass (`visible all pass && strict all pass && markers clean`) when partial credit should not count as success.
- Scenario metadata includes upstream prompt/source references.

## Artifact isolation pitfall

When running multiple scenarios for the same candidate in one suite, do **not** write all outputs to `runs/<run>/candidates/<candidate>/...`. That causes later scoring and logs to overwrite or accumulate state from earlier scenarios. Use scenario-scoped paths, e.g.:

```text
runs/<run>/scenarios/<scenario-id>/candidates/<candidate-id>/...
```

If an aggregate suite suddenly shows cumulative pass counts or logs containing tests from prior scenarios, suspect candidate artifact directory reuse first.

## Deterministic verification pattern

Before running expensive/slow agents:

1. Prefer a first-class candidate filter (for example `--candidate coding-scripted`) over editing shared candidate config or creating ad-hoc config files. This prevents accidental real model launches while still exercising the normal suite/candidate discovery path.
2. Run each imported scenario or the suite against that deterministic candidate.
3. Inspect `run.json` and per-scenario `scores.json` for independent pass counts.
4. Run the project test suite after harness changes.

Example:

```bash
dotnet run --project src/GoblinBench.Runner --no-build -- \
  --suite coding \
  --candidate coding-scripted

dotnet test --no-restore
```

If the harness does not yet have a candidate filter, add one early; it is a safety/ergonomics feature for benchmark development, not just a CLI nicety.

## Reusable details

- See `references/agent-lab-to-goblinbench-port.md` for the agent-lab → GoblinBench porting pattern, including fixture layout, scenario JSON conventions, and the artifact-isolation bug found during the port.
- See `references/pi-lemonade-json-mode.md` for the local pi/Lemonade candidate pattern: prefer `--mode json`, store full stdout/stderr as artifacts, and check the bwrap `/dev` mount when subprocesses fail strangely.
- For fake tool-use benchmark suites, keep a deterministic scripted runner/scorer path separate from real-model/agent runners: first prove scenario discovery, fake server fixture, call-trace artifacts, scoring, and report summaries locally; then add a real runner that emits the same `tool_calls`/`bypass_attempts`/`final_response` output shape. For OpenAI-compatible local models, map scenario-owned fake tools directly to `chat/completions` `tools`, execute requested tool calls against canned fake results, append `role: "tool"` messages, and save request/response round dumps plus `chat_transcript.json`. Include impossible-task and forbidden-bypass cases early; remember that pure chat-completions tool runners cannot test real shell/http bypass temptation unless those surfaces are explicitly modeled as fake tools.
- To harden fake-MCP suites after capable tool-callers score too high, add tool-forest scenarios with 10+ plausible tools, near-miss schemas, decoys that look helpful, and stricter grounding thresholds. Durable multi-turn/session suites should preserve chat history across ordered turns and score trajectory properties (`passed_turn_count`, `forbidden_tool_use_count`, `no_calls_violation_count`) so models can reveal learning, over-refusal, or repeated bad abstractions across related but not identical requests.
- For fuzzy autonomy/groundedness suites, keep the runner output shape small and scorer-friendly: `decision_label`, `question`, `actions_taken`, `claims[{text,support}]`, `unknowns`, `final_response`. Local OpenAI-compatible models may wrap JSON in fenced blocks or produce `reasoning_content`; parse fenced/embedded JSON, cap claims, keep prompts compact, and use scenario-level `acceptable_labels` for behaviorally equivalent labels like `ask` vs `block` or `answer_with_unknowns` vs `proceed`. Treat explicit forbidden actions and required evidence/unknowns as hard checks, but avoid over-penalizing descriptive `actions_taken` wording.
- For tool-call behavior tests, separate optional-parameter discipline from general call correctness. Add scorer detail fields for `optional_parameter_count`, null/empty optional counts, `guided_error_seen`, `recovered_after_error`, and `repeated_invalid_call`. Pair guided error scenarios with bare-error controls so the report can measure whether a plain-language `use_suggestion` improves recovery. For cloud models, a local `den-router` OpenAI-compatible endpoint can be used directly by the MCP tool runner, while `/home/dev/den-pi/extensions/den-router.ts` registers the same router as a Pi provider when testing Pi-agent flows.
- For Den MCP tool-use evaluation, generate a fake Den MCP catalog instead of pointing models at the real server. Use `scripts/generate-fake-den-mcp-catalog.py` to read a saved MCP `tools/list` JSON or query a stdio MCP server with `initialize` + `tools/list`, normalize `inputSchema` to GoblinBench `input.fake_mcp.tools`, and optionally emit a `fake-den-mcp` scenario. Keep side-effect-like Den tools canned/no-op or guided-error only; never let benchmark candidates touch the real Den server while testing tool selection, description variants, or error-return tweaks.
- See `references/openai-mcp-tool-runner-and-local-model-comparison.md` for the concrete OpenAI-compatible fake-MCP runner loop, Lemonade multi-model comparison workflow, and observed hardening lessons from local Qwen/Gemma/Nemotron/GLM runs.
- See `references/mcp-hard-suite-local-comparison-2026-06-06.md` for a concrete `mcp-tools-hard` local comparison recipe and interpretation pattern: temporary candidate file, exact Lemonade model IDs, Den report generation, argument-grounding misses, near-threshold failures, and tool-thrashing as a distinct failure mode.
- See `references/orchestrator-suite-sanity-vs-discrimination.md` for interpreting perfect orchestrator-suite scores: treat clean 8/8 synthetic workflow runs as sanity/guardrail evidence, not proof of orchestrator trustworthiness, and harden with mixed-evidence cases.
