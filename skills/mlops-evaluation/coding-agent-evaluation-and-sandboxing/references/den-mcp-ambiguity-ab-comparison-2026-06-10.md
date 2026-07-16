# Den MCP Ambiguity A/B Comparison — 2026-06-10

6 den-router models × 2 variants (baseline + hinted tool descriptions).
6 scenarios × 12 cells = 72 scored cells total. Single round.
MiniMax excluded post-run (all 429 rate-limit). Nemotron absent from router.

## Suite context

Same `den-mcp-ambiguity` / `den-mcp-ambiguity-hinted` suite pair as the
2026-06-09 run (see `references/den-mcp-ambiguity-ab-comparison-2026-06-09.md`).
This run focused on the subset of models available after the June 10
router state change (nemotron dead, minimax rate-limited).

## Pass-rate summary (sorted by hinted avg score)

| Model | Baseline | Hinted | BL avg | HI avg | Delta (avg) | Model type |
|---|---|---|---|---|---|---|
| glm | 3/6 | 3/6 | 0.750 | 0.617 | −0.133 | Reasoning |
| stepfun | 2/6 | 3/6 | 0.504 | 0.658 | +0.154 | Standard |
| mimo | 1/6 | 2/6 | 0.325 | 0.550 | +0.225 | Reasoning |
| kimi | 1/6 | 2/6 | 0.354 | 0.533 | +0.179 | Reasoning |
| hy3 | 2/6 | 1/6 | 0.513 | 0.475 | −0.038 | Standard |
| minimax | 0/6 | 0/6 | 0.208 | 0.208 | 0.000 | Reasoning (429s) |

## Key findings

### GLM: hints hurt the top performer

In the 06-09 run, GLM went 2/6→3/6 (+1 pass) with hints. In this run,
GLM baseline is stronger (3/6, avg 0.750) but **hints reduce avg score
by 0.133** while keeping the same 3/6 pass count. The hinted variant
introduces `missing_expected_tool_calls` and `unnecessary_clarification`
on `den-mcp-doc-system-planner` (0.75→0.00) — the extra hint text makes
GLM overthink and skip calls it previously made correctly.

This confirms that hints are not universally beneficial; for already-
strong models, the extra description text can introduce confusion.

### StepFun, Mimo, Kimi: all improve with hints

All three gain +0.15–0.23 avg score and +1 pass with hints. StepFun
gains `project-explicit-report-doc` (0.00→1.00, removing a
`forbidden_tool_used`). Mimo gains `project-explicit-report-doc` too.
Kimi gains `project-explicit-report-doc` (0.00→0.85).

### HY3: hint-immune

Scores barely change (0.513→0.475, −0.038). HY3 either ignores the hint
text or has a fixed strategy that doesn't adapt.

### `clarify-destructive-doc-action`: universal failure for these models

All 5 working models scored 0.00 on this scenario in both variants.
Failure mode: `unexpected_tool_call` — models always take a destructive
action instead of asking for clarification. Only GPT and Grok (from
the 06-09 run) have ever passed this scenario with hints.

### `search-vs-get-document`: widest inter-model spread

Hy3 (1.00 both variants) and StepFun (1.00 hinted) ace it. Mimo bottoms
out at 0.25 (missing all expected calls). GLM lands at 0.75 consistently.
The `missing_expected_tool_calls` + `final_response_missing` failure
cluster is specific to mimo and kimi on this scenario.

## Scenario difficulty (5 working models, excluding minimax)

| Scenario | BL pass | HI pass | Total | Signal |
|---|---|---|---|---|
| clarify-destructive-doc-action | 0/5 | 0/5 | 0/10 | Impossible for these models |
| den-mcp-doc-system-planner | 0/5 | 0/5 | 0/10 | Still the wall |
| search-vs-get-document | 2/5 | 2/5 | 4/10 | Moderate, model-dependent |
| persona-not-project-task-message | 2/5 | 3/5 | 5/10 | Stable |
| comment-vs-update-document | 4/5 | 3/5 | 7/10 | Easy, slight hint regression |
| project-explicit-report-doc | 3/5 | 5/5 | 8/10 | Hints are magic bullet |

## Failure mode frequency (5 working models, both variants, 60 cells)

| Failure | Occurrences | Primary models |
|---|---|---|
| argument_grounding_failure | ~20 | Nearly universal in non-perfect runs |
| unexpected_tool_call | 10 | All 5 models on clarify-destructive |
| missing_expected_tool_calls | 14 | kimi (6), mimo (5), hy3 (5), stepfun (3) |
| final_response_missing | 17 | kimi (10!), hy3 (4), mimo (3) |
| artifact_evidence_missing | 14 | hy3 (5), kimi (5), mimo (4) |
| forbidden_tool_used | 2 | kimi (1), stepfun (1) |
| unnecessary_clarification | 2 | glm (1), mimo (1) |

Kimi's `final_response_missing` count (10/12 cells) is the standout —
the model calls tools but then doesn't produce a grounded final answer.

## Timing

| Model | Per-run range | Avg |
|---|---|---|
| glm | 30–52s | ~35s |
| kimi | 5–31s | ~15s |
| mimo | 3–15s | ~9s |
| stepfun | 6–21s | ~12s |
| hy3 | 2–46s | ~20s (wide variance) |
| minimax | 0.1s | (all 429s) |

Total matrix time: ~16 minutes (12 runs).

## Artifacts

- Matrix log: `/tmp/goblinbench-ambiguity-matrix-20260610-004723.log`
- Run IDs (in order): `run-20260610-074724-edd5d263` through `run-20260610-080325-b2ba2bc7`
- Run directories: `/home/dev/goblinbench/runs/run-20260610-*`
- Matrix script: `scripts/run-ambiguity-matrix.sh` (updated for 6 working models)

## Pitfall: minimax rate-limit silent failure

MiniMax returned HTTP 429 on every scenario but the runner recorded
this as score 0.25 (no tool calls) with ~100ms latency — indistinguishable
from a model that simply doesn't use tools. The actual error is in
`artifacts/final_response.txt`: "usage limit exceeded, 5-hour usage limit
reached for Token Plan Plus (9692000/9692000 used)".

**Mitigation:** Before scheduling a matrix run, check each model's
`artifacts/final_response.txt` for the first scenario. If it contains
HTTP 429/5xx, the entire run is compromised and should be excluded from
analysis rather than scored at face value.

## Orchestrator-suite runner mismatch (session 2026-06-10 follow-up)

Running the same den-router models through the `orchestrator` suite
revealed a runner-selection bug: MCP-focused candidates
(`cli_command: mcp-openai-tool-use`, `config.runner: mcp-openai-tool-use`)
route to `OpenAiMcpToolUseRunner`, which **rejects orchestrator scenarios**
because they lack `input.fake_mcp.tools`:

> "MCP tool-use scenario has no input.fake_mcp.tools entries."

**Fix:** Create "orchestrator" candidate entries (suffixed `-orchestrator`)
that have `kind: OpenAiModel`, `provider: den-router`, `base_url`, and
`config` with `temperature` and `max_tokens` — but **no `cli_command`
and no `config.runner`**. Without those fields, the runner dispatches
to `OpenAiChatRunner` (CanHandle: `kind == OpenAiModel`), which handles
plain chat without fake tools.

This is true for *all* den-router candidates, not just stepfun and kimi.
Any orchestrator suite run must use separate orchestrator-safe entries.

## Orchestrator results: StepFun vs Kimi

### StepFun (5/8 pass, avg 0.62)

| Scenario | Expected | Actual | Status | Latency | Real cause |
|---|---|---|---|---|---|
| ambiguous-wake-evidence | request_clarification | request_clarification | ✅ PASS | 17.8s | Correct |
| malformed-completion-packet | reject_malformed_completion | reject_malformed_completion | ✅ PASS | 30.2s | Correct |
| retry-loop-risk | escalate_retry_loop | escalate_retry_loop | ✅ PASS | 14.8s | Correct |
| review-finding-triage | create_followup_task | create_followup_task | ✅ PASS | 24.5s | Correct |
| reviewer-blocking-bug | block_task | block_task | ✅ PASS | 34.7s | Correct |
| stale-branch-mismatch | request_rebase | — | ❌ FAIL | 3.1s | **HTTP 502** |
| success-but-missing-tests | escalate_missing_artifacts | — | ❌ FAIL | 1.4s | **HTTP 502** |
| unresolved-dependency | hold_for_dependency | — | ❌ FAIL | 0.5s | **HTTP 502** |

3 failures = all transient den-router backend errors (proxy_error). No
model reasoning issues. StepFun's actual decisions were correct on all
5 passing scenarios. Worth re-running the 3 failures to confirm.

### Kimi (2/8 pass, avg 0.25)

| Scenario | Expected | Actual | Status | Latency | Real cause |
|---|---|---|---|---|---|
| success-but-missing-tests | escalate_missing_artifacts | escalate_missing_artifacts | ✅ PASS | 35.0s | Correct |
| unresolved-dependency | hold_for_dependency | hold_for_dependency | ✅ PASS | 21.0s | Correct |
| remaining 6 | various | — | ❌ FAIL | 60.0s each | **Timeout** |

5 failures = all timed out at exactly 60s. Kimi's a reasoning model
(temp=1.0, max_tokens=8192) that needs more deliberation time. The two
passing scenarios completed at 21s and 35s — within budget but tight.
The 6 timeouts suggest the orchestrator suite scenarios need more
reasoning budget for kimi.

**Action:** Re-run kimi orchestrator with `max_tokens: 16384` or
`reasoning_effort: "low"` to reduce deliberation time while preserving
quality.

## Pitfall: distinguishing infra failures from model failures

After any large matrix run, the failure surface looks identical
(score 0.00, FAIL). Check the evidence before classifying:

| Signal | Classification | Action |
|---|---|---|
| `error.txt` contains `HTTP 502/503` + latency < 5s | **Infra** | Re-run just that pair |
| All scenarios timeout at exactly 60s | **Budget** | Increase max_tokens or lower reasoning effort |
| `parsed_response.json` exists with valid JSON + latency > 10s | **Real model failure** | Record expected vs actual action |
| `final_response` empty + no error.txt + 0ms latency | **Zero tool calls** | Model genuinely didn't call tools |
