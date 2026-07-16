# Orchestrator suite: sanity check vs discriminating eval

Session lesson from GoblinBench orchestrator and coding-agent evaluation work.

## What happened

A local Qwen orchestrator run passed the full GoblinBench `orchestrator` suite:

- Candidate: `qwen3-35b-local`
- Model: `Qwen3.6-35B-A3B-GGUF`
- Suite: `orchestrator`
- Result: `8/8` pass, `100%`
- Avg latency: about `27.5s`
- Example run artifact: `/home/dev/goblinbench/runs/run-20260606-041050-b684beb2`
- Den report slug: `goblinbench/bench-report-orchestrator-20260606-0416`

The suite scenarios covered realistic Den/Hermes orchestration actions:

- ambiguous wake evidence -> `request_clarification`
- success but missing tests/artifacts -> `escalate_missing_artifacts`
- stale branch/head mismatch -> `request_rebase`
- style-only review finding triage -> `create_followup_task`
- unresolved dependency under queue pressure -> `hold_for_dependency`
- malformed completion packet -> `reject_malformed_completion`
- reviewer blocking bug -> `block_task`
- retry loop risk -> `escalate_retry_loop`

## Interpretation pattern

Do **not** overstate a perfect score on a clean synthetic orchestrator suite.

Treat this kind of result as:

1. **Good sanity/guardrail evidence** — the model can emit the required schema and choose the obvious safe action in canonical workflow cases.
2. **Not yet strong trust evidence** — if several plausible local models also get `8/8`, the suite is likely too easy or too signposted to discriminate orchestrator suitability.
3. **Latency-relevant but not necessarily disqualifying** — 20–35s can be acceptable for deliberate orchestration decisions, but it should be reported separately from action quality.

## Reporting guidance

When reporting orchestrator eval results, separate:

- runner health: did the candidate complete and emit parseable output?
- schema compliance: did it produce the required fields?
- decision accuracy: did `next_action` match the expected action and avoid forbidden actions?
- latency: how long did the deliberation take?
- suite discriminative power: are scenarios adversarial enough to reveal differences?

Useful phrasing:

> "This looks strong, but maybe suspiciously strong: the suite is currently a sanity/guardrail eval, not a hard trust benchmark. We need harder mixed-evidence cases before treating this as proof of orchestration readiness."

## Next suite-hardening ideas

Add cases where the correct action is not simply conservative:

- A worker reports missing tests, but a separate validator packet contains valid test evidence.
- Reviewer says `blocking`, but the finding is stale/superseded by a later review round.
- Dependency appears unresolved in a cached task summary, but a fresh Den projection says it is done.
- Multiple worker completions conflict; the newest packet is malformed but an older valid packet exists.
- User queue pressure is high, but there is a safe partial preparatory task that does not violate dependency boundaries.
- Retry loop appears likely, but a new failure signature indicates a changed condition worth one targeted retry.
- Direct-agent wake evidence is ambiguous, but a checkpoint response or assignment state provides enough provenance to decide.

## Run Interpretation: infra failures vs model failures

A failing orchestrator run can mean three very different things. Check the evidence before drawing conclusions:

### 1. Empty response at <2s — HTTP 502/503 from den-router

The den-router backend can intermittently fail with "All backends failed:
backend returned HTTP 503." The runner writes the HTTP 502 error into
`final_response` and scores the scenario as FAIL (score 0.00), but the
**failure is infrastructure, not model reasoning**.

**Evidence:** `artifacts/error.txt` contains `HTTP 502: ... proxy_error`,
latency < 5s, `output.json` `final_response` is empty or contains the
HTTP error string.

**Action:** Re-run the affected (candidate, scenario) pair. These errors
are usually transient.

### 2. Timeout at ~60s — reasoning model too slow for the budget

Reasoning models (kimi, mimo, glm via den router) expend `max_tokens`
on internal `reasoning_content` before producing tool calls or final
text. The orchestrator suite scenarios have no hard-coded long timeout,
but the runner's scenario timeout (30s) or the HTTP client's timeout
can effectively cap a reasoning model at 60s.

**Evidence:** All failing scenarios hit the same ~60s timestamp,
2/8 pass rate where the 2 passing scenarios completed in 15–35s.

**Action:** Increase `max_tokens` (8192→16384) or add a longer HTTP
timeout. Alternatively, try `reasoning_effort: "low"` to reduce
deliberation time. See the reasoning-effort config pattern in
`den-router-candidate-comparison.md`.

### 3. Genuine model wrong answer — scored FAIL with actual response

**Evidence:** `parsed_response.json` or `output.json` contains a
complete JSON response with `next_action` field, latency > 10s, and
the `orchestrator-decision` scorer's `failure_categories` list includes
reason strings like `wrong_action` or `missing_required_fields`.

This is a real model-level failure. Record the expected vs actual
action and failure category in the report.

## Contamination pattern: `scripted_response` leaking into the prompt

A separate but related failure mode to "suite is too easy": the scenario JSON can accidentally include the expected answer inside the model-visible prompt, and the model will reproduce it verbatim, scoring a perfect pass without reasoning.

**Concrete instance observed.** The `orchestrator.ambiguous-wake-evidence` scenario contained a `scripted_response` block embedded in the prompt text. The Qwen 3.5 35B local candidate's output reproduced that block nearly word-for-word:

> "The wake event carries a direct contradiction: status='completed' but exit_code=1. Neither field can be trusted without corroborating evidence. The worker log is unavailable and the artifact directory is empty..."

The model even noted in its reasoning: *"The prompt actually includes a `scripted_response` at the end, which seems to be an example or the expected output format. I should just output the JSON matching that structure."* A perfect 1.00 score on this scenario is therefore contaminated — the model read the answer key.

**How to detect this in a run:**

1. Compare the candidate's `reasoning_content` and final `content` against the scenario's `scripted_response` (or any block in the prompt that looks like a sample answer). If the model reproduces the wording and explains in its reasoning that it saw "an example," the score is not trustworthy.
2. Look for reasoning traces that mention "example," "template," "matches the prompt's `scripted_response`," or "expected output format."
3. Run a model variant that is known to be weaker than the candidate; if it also scores 1.00 on the same scenario, the suite is contaminated or too easy.

**How to fix:**

- Move `scripted_response` out of the prompt text. Put it in a separate scenario metadata field that the runner reads but the prompt does not include. The runner / scorer uses it for replay and for the `scripted_final_response` fallback; the model never sees it.
- Audit every scenario for similar patterns: `example:`, `expected:`, `sample output:`, any JSON block inside the prompt that looks like a complete answer.
- After fixing, re-run the suite. Models that previously scored 1.00 should drop to a realistic spread.

**Related coding-agent lesson**

When a real model run is contaminated by runner failure (for example pi/Lemonade `--mode text` exit 137), do not use partial scores as clean model-quality metrics. Fix runner health first, then rerun the full suite in the stable mode (for pi/Lemonade local coding agents, prefer `--mode json`).
