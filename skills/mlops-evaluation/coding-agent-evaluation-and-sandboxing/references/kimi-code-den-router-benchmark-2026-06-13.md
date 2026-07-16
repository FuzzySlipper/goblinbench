# Kimi Code via den-router benchmark notes (2026-06-13)

Session-specific benchmark reference for `kimi-code` after release through the Den router.

## Provider/model facts

- Den-router model id: `kimi-code`.
- Smoke response reported upstream model: `kimi-k2.7-code`.
- Like `kimi`, `kimi-code` requires `temperature: 1.0`; `temperature: 0.2` returns HTTP 400: `invalid temperature: only 1 is allowed for this model`.
- Basic `max_tokens: 64` smoke with no temperature or `temperature: 1.0` returned 200 and content.
- During large suite runs, Moonshot returned intermittent `HTTP 429` with message `The engine is currently overloaded, please try again later`; targeted retries after short waits succeeded for most affected cells.

## Candidate shapes used

Separate candidate shapes are still required by suite family:

- MCP/tool-use suites: `OpenAiModel` with `cli_command: "mcp-openai-tool-use"`, `config.runner: "mcp-openai-tool-use"`, `temperature: 1.0`, `max_tokens: 8192`, `max_tool_rounds: 6`.
- MCP session suite: `OpenAiModel` with `cli_command: "mcp-openai-session"`, `config.runner: "mcp-openai-session"`, `temperature: 1.0`, `max_tokens: 8192`.
- Orchestrator suite: plain `OpenAiModel` with no `cli_command` or `config.runner`, `temperature: 1.0`, `max_tokens: 8192`.
- Autonomy/grounding suites: `OpenAiModel` with `cli_command: "fuzzy-openai"`, `config.runner: "fuzzy-openai"`, `temperature: 1.0`, `max_tokens: 8192`.
- Coding suite: `CodingAgent` pi wrapper using den-router provider extension and model `kimi-code`; skip `coding.roman-numerals` and `coding.export-report` for the cloud coding subset.

## Final clean run-set results

Final run set: `kimi-code-relevant-final-20260613-0852`.
Raw campaign/retry artifacts: `runs/kimi-code-relevant-20260613-0820/`.
Den doc: `goblinbench/kimi-code-relevant-benchmark-20260613`.

| Suite | Pass | Avg score | Avg latency | Runner failures |
|---|---:|---:|---:|---:|
| coding | 2/6 | 0.6745 | 46.1s | 5 |
| mcp-tools | 7/8 | 0.8594 | 10.2s | 0 |
| mcp-tools-hard | 1/3 | 0.8167 | 19.3s | 0 |
| fake-den-mcp | 1/1 | 1.0000 | 4.8s | 0 |
| tool-call-behavior | 4/4 | 0.9812 | 7.9s | 0 |
| den-mcp-ambiguity | 2/6 | 0.6792 | 13.7s | 0 |
| den-mcp-ambiguity-hinted | 4/6 | 0.8958 | 9.7s | 0 |
| mcp-session | 1/1 | 1.0000 | 19.6s | 0 |
| orchestrator | 8/8 | 1.0000 | 9.6s | 0 |
| autonomy-calibration | 2/3 | 0.6167 | 9.4s | 0 |
| evidence-grounding | 3/3 | 0.8000 | 33.2s | 0 |

## Interpretation notes

- Strong: orchestrator, MCP session, tool-call-behavior, evidence-grounding, basic MCP tools.
- Mixed: hinted Den MCP ambiguity improved over baseline (`4/6` vs `2/6`), autonomy calibration `2/3`, hard MCP forests `1/3` but partial scores were high (`0.75`) on misses.
- Coding should be interpreted as runner-health + scoring separately: scoring found 2/6 pass cells, but 5/6 candidate executions reported runner failure (`Agent exited 0 but produced no file changes` or code 137) despite some useful patch/test results.

## Campaign pattern lessons

- For overloaded cloud providers, do not rerun the whole matrix blindly. First identify `HTTP 429` contaminated cells from `candidate_result.error`, then rerun affected suites/cells and compose a final run-set from clean artifacts.
- If only some scenarios in a suite rerun cleanly, create one-scenario run rows for the final run-set so aggregate CLI reports do not double-count stale suite-level failures.
- The `gb-results.py` run-set importer is run-level, not scenario-level. A final composite run-set can include many one-scenario runs for a single suite when targeted retries are needed.
