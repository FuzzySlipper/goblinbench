# Den MCP Ambiguity A/B Comparison — 2026-06-09

13 den-router models × 2 variants (baseline + hinted tool descriptions).
6 scenarios × 26 cells = 156 scored cells total.
3 rounds: round 1 (6 models), round 2 (4 models, den-router fix), round 3 (3 models).

## Suite context

The `den-mcp-ambiguity` suite tests tool-selection discipline under
natural-language ambiguity: mixed Den project ids, agent/persona phrases,
document/task operations, destructive-action hesitancy. Models see Den-shaped
fake MCP tool schemas with 13 tools. Scoring uses strict argument-field
grounding (e.g. `project_id` in tool args, not just mentioned in free text).

The hinted variant appends `TOOL HINT:` blocks to tool descriptions and
`project_id` schema fields clarifying project routing, persona-vs-project
language, and destructive-action semantics. Prompts, fake results, expected
calls, and thresholds are identical.

## Pass-rate summary (sorted by hinted pass count)

| Model | Baseline | Hinted | Delta | Model type |
|---|---|---|---|---|
| gpt | 2/6 | 5/6 | +3 | Standard |
| stepfun | 2/6 | 4/6 | +2 | Standard |
| deepseek-pro | 1/6 | 4/6 | +3 | Reasoning |
| deepseek-flash | 3/6 | 3/6 | 0 | Standard |
| glm | 2/6 | 3/6 | +1 | Reasoning |
| grok | 2/6 | 3/6 | +1 | Standard |
| hy3 | 2/6 | 3/6 | +1 | Standard |
| mimo-pro | 1/6 | 3/6 | +2 | Reasoning |
| minimax | 1/6 | 3/6 | +2 | Reasoning |
| kimi | 0/6 | 3/6 | +3 | Reasoning |
| nex-n2-pro | 1/6 | 2/6 | +1 | Reasoning |
| mimo | 1/6 | 1/6 | 0 | Reasoning |
| nemotron | 1/6 | 1/6 | 0 | Standard |

## Key findings

### Scenario difficulty

| Scenario | BL pass | HI pass | Total | Signal |
|---|---|---|---|---|
| den-mcp-doc-system-planner | 0/13 | 0/13 | 0/26 | Impossible — "den system planner" tricks all models |
| clarify-destructive-doc-action | 0/13 | 7/13 | 7/26 | Hints unlock restraint; GPT/Grok join reasoning models |
| search-vs-get-document | 3/13 | 5/13 | 8/26 | Moderate |
| persona-not-project-task-message | 5/13 | 6/13 | 11/26 | Stable across variants |
| comment-vs-update-document | 7/13 | 7/13 | 14/26 | Most-passed baseline scenario |
| project-explicit-report-doc | 4/13 | 13/13 | 17/26 | Hints are a magic bullet — every model passes hinted |

### Interpretation

1. **Reasoning models respond more to hints** — deepseek-pro (+3), kimi
   (+3), mimo-pro (+2), minimax (+2) all show big deltas. Non-reasoning
   models (deepseek-flash, nemotron) don't budge. The extra hint text
   seems to give reasoning models a chain-of-thought anchor.

2. **`project-explicit-report-doc` is perfectly solved by hints** — 3/10
   → 10/10. The TOOL HINT about project routing ("GoblinBench →
   goblinbench") is universally absorbed.

3. **`den-mcp-doc-system-planner` is the wall** — 0/10 in both variants.
   The "den system planner" phrasing overrides even explicit hints. This
   is the discriminating scenario for real tool-use discipline.

4. **StepFun (Step 3.7 Flash) is the surprise performer** — tied with
   deepseek-pro at 4/6 hinted despite being a smaller model.

5. **Mimo base is noise-sensitive** — hints make it worse on comment-vs-update
   (-0.60) and persona-not-project (-0.70). Extra description text
   introduces confusion rather than clarity.

6. **Tool discipline ≠ coding ability** — models that dominate coding
   benchmarks don't dominate here. This suite may measure orchestrator
   fitness more than raw capability.

7. **GPT (via OpenRouter) tops the board at 5/6 hinted** — the only model
   to pass 5 of 6 scenarios. Still can't crack `den-mcp-doc-system-planner`
   (nobody can). Gains the most from hints: clarify-destructive and
   project-explicit-report-doc both flip from fail to pass.

8. **Grok is solid mid-range** (2→3 with hints). Handles clarify-destructive
   and project-explicit-report well but doesn't crack search-vs-get or
   persona-not-project.

9. **nex-n2-pro underperforms** (1→2). Runner errors on ~4/6 scenarios
   ("response did not include choices[0].message") — likely an OpenRouter
   streaming framing issue with this model. Slow (~3 min/run).

### Pitfall: kimi temperature

Kimi requires `temperature: 1.0` (HTTP 400 otherwise). This does NOT
surface in a basic smoke probe without temperature. The initial matrix run
scored kimi 0/6 with all-400 errors. After fixing to `temperature: 1.0`,
kimi achieved 3/6 hinted.

### Pitfall: backend outages mid-matrix

During the first matrix run, deepseek-flash hinted hit HTTP 502 ("All
backends failed") on 5/6 scenarios. The 0/6 score was infrastructure, not
model capability. Re-running produced 3/6. Always check per-scenario errors
before interpreting a 0/6 result.

### Pitfall: nex-n2-pro response parsing

nex-n2-pro via OpenRouter intermittently returns responses that omit
`choices[0].message` entirely, causing "OpenAI-compatible response did not
include choices[0].message" runner errors. This affected 4/6 scenarios in
both baseline and hinted runs. The model itself produces correct tool calls
when responses parse successfully, but the error rate makes it unreliable
for automated scoring without a retry mechanism.

### Pitfall: report generator suite filter

Candidate IDs are identical across baseline and hinted variants. Passing
all run IDs to a single `--suite den-mcp-ambiguity` report silently drops
hinted runs (their scenario IDs start with `den-mcp-ambiguity-hinted.`).
Generate separate reports per variant with matching `--suite` filters.

## Artifacts

- Baseline report: `runs/den-mcp-ambiguity-report/baseline-clean.md/.json/.html`
- Hinted report: `runs/den-mcp-ambiguity-report/hinted-clean.md/.json/.html`
- Round 2 baseline: `runs/den-mcp-ambiguity-report/r2-baseline.md/.json/.html`
- Round 2 hinted: `runs/den-mcp-ambiguity-report/r2-hinted.md/.json/.html`
- Round 3 baseline: `runs/den-mcp-ambiguity-report/r3-baseline.md/.json/.html`
- Round 3 hinted: `runs/den-mcp-ambiguity-report/r3-hinted.md/.json/.html`
- Matrix run script: `scripts/run-ambiguity-matrix.sh`
