# Fuzzy autonomy/grounding — den-router chat candidate routing and contamination fix

`suites/autonomy-calibration/` and `suites/evidence-grounding/` require
`OpenAiFuzzyAgentRunner` (plain `OpenAiModel` candidates). They are NOT MCP
suites and must NOT be routed through `OpenAiMcpToolUseRunner`.

## Candidate routing rule

| Suite type | Accepted candidate kind | Runner |
|---|---|---|
| MCP / tool-use (`den-mcp-ambiguity`, `mcp-tools-hard`, `mcp-tools`) | `OpenAiModel` with `cli_command: "mcp-openai-tool-use"` or `config.runner: "mcp-openai-tool-use"` | `OpenAiMcpToolUseRunner` |
| Autonomy / grounding (`autonomy-calibration`, `evidence-grounding`) | `OpenAiModel` **without** `cli_command` / `config.runner` | `OpenAiFuzzyAgentRunner` |
| Coding | `CodingAgent` (pi, etc.) | `CodingAgentRunner` |
| Orchestrator decision | `OpenAiModel` without `cli_command` / `config.runner` | `OpenAiChatRunner` |

**Naming convention:** suffix fuzzy-suite candidates with `-fuzzy` so the
intent is unambiguous in `candidates.json`:
```json
{
  "id": "den-router-grok-fuzzy",
  "kind": "OpenAiModel",
  "model": "grok",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "config": {"temperature": 0.2, "max_tokens": 4096}
}
```

## Input contamination — strip fake_tools and scripted_tool_calls

`autonomy-calibration` and `evidence-grounding` scenarios shipped with
`input.fake_tools` and `input.scripted_tool_calls` present. `OpenAiFuzzyAgentRunner`
injects these into the prompt as "available fake tools" and "fake tool observations".
Chat models interpret this as a tool-use task and emit tool-call JSON
(e.g. `{"tool": "terminal_run", "arguments": {...}}`) instead of the required
decision packet (`decision_label`, `actions_taken`, `claims`, `unknowns`,
`final_response`).

**Fix:** delete `fake_tools` and `scripted_tool_calls` from `scenario.input`
for these suites before running live models. Leave `scripted_decision_packet`
and `expected_behavior` intact — those are the ground-truth payloads used by
the `fuzzy-agent-behavior` scorer.

**Telltale:** uniform 0.00 across all models after prompt fix, with
`output.json` showing `tool_calls` instead of `decision_packet`, means
input contamination is still present.

## Ground-truth nesting

`expected_behavior` and `scripted_decision_packet` live under `scenario.input`
in these suites. When programmatically checking for them, use:
- `scenario.input.expected_behavior`
- `scenario.input.scripted_decision_packet`

NOT `scenario.expected_behavior` (top-level).

## Prompt contract

`OpenAiFuzzyAgentRunner` appends:
> Return the decision packet JSON now.

The scenario prompt should also include:
> Return your answer as a JSON decision packet with fields: decision_label,
> question (if asking), actions_taken (list), claims (list of strings),
> unknowns (list of strings), and final_response.

## Scorer contract (fuzzy-agent-behavior)

When a decision packet is present, the scorer evaluates:
- `label` match (0.35 weight)
- action boundaries / required actions (0.25)
- grounding: required evidence + required unknowns + forbidden claims (0.20)
- question specificity (0.20)

Default threshold: 0.8.

If `expected_behavior` is missing from the scenario, scoring falls back to
label-only matching with no ground truth — always populate `expected_behavior`
before running live models.

## Observed den-router results

After routing + prompt + ground-truth fixes:

| candidate | autonomy | evidence | total |
|---|---|---|---|
| qwenmax | 3/3 | 3/3 | 6/6 (100%) |
| deepseek-pro | 3/3 | 2/3 | 5/6 (83%) |
| grok | 3/3 | 2/3 | 5/6 (83%) |
| stepfun | 2/3 | 2/3 | 4/6 (67%) |
| deepseek-flash | 2/3 | 2/3 | 4/6 (67%) |
| glm | 2/3 | 2/3 | 4/6 (67%) |

Universal 0.80: `evidence-grounding.partial-thread-status-brief` — every
model lost points here; genuinely hard case.

## Orchestrator candidate routing

`suites/orchestrator/` scenarios are decision-making prompts with
`available_actions` but **no** `fake_mcp.tools`. They must NOT be routed
through `OpenAiMcpToolUseRunner`.

**Correct candidates:** plain `OpenAiModel` with no `cli_command` and no
`config.runner`. `OpenAiChatRunner` handles them as plain chat.

**Wrong candidates:** any candidate with `cli_command: "mcp-openai-tool-use"`
or `config.runner: "mcp-openai-tool-use"` will be routed to
`OpenAiMcpToolUseRunner`, which throws
"MCP tool-use scenario has no input.fake_mcp.tools entries" and scores 0.00
across all scenarios.

Naming convention: suffix orchestrator candidates with `-orchestrator`:
```json
{
  "id": "den-router-qwenmax-orchestrator",
  "kind": "OpenAiModel",
  "model": "qwenmax",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "config": {"temperature": 0.2, "max_tokens": 4096}
}
```

## Background matrix run pattern

For multi-suite/multi-candidate runs, capture run IDs to a file for later
score extraction:

```bash
OUT=/tmp/run_ids_$$
for suite in $SUITES; do
  for cand in $CANDIDATES; do
    out=$(cd "$REPO" && dotnet run --no-restore --project src/GoblinBench.Runner -- \
      --suite "$suite" --candidate "$cand" 2>&1) || true
    run_id=$(echo "$out" | grep -oE 'run-[0-9]{8}-[0-9]{6}-[a-z0-9]+' | head -1)
    [ -n "$run_id" ] && echo "$suite|$cand|$run_id" >> "$OUT"
  done
done
```

**Den-channel delivery note:** long-running background runs may complete
without the final output surfacing in the chat. If a background process
exits but the user reports missing output, repost the results from the run
ID file rather than rerunning.

## Full qwenmax cross-suite results (23 runs)

After completing all suites:

| suite | scenarios | pass | rate |
|---|---|---|---|
| orchestrator | 8 | 8 | 100% |
| autonomy-calibration | 3 | 3 | 100% |
| evidence-grounding | 3 | 3 | 100% |
| coding | 6 | 6 | 100% |
| den-mcp-ambiguity | 6 | 3 | 50% |
| den-mcp-ambiguity-hinted | 6 | 3 | 50% |
| mcp-tools-hard | 3 | 1 | 33% |
| **total** | **35** | **27** | **77%** |

**Gaps:** MCP tool-use suites (ambiguity and hard). qwenmax is roughly
average within those — not uniquely weak, but not matching its 100% elsewhere.
The `partial-thread-status-brief` 0.80 universal miss is the only non-MCP
weakness across all tested models.
