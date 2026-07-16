# Kimi Code rerun + GLM52 benchmark (2026-06-16)

Campaign: `/home/dev/goblinbench/runs/kimi-code-glm52-relevant-20260615-2357/`
Final run set: `kimi-code-glm52-relevant-final-20260616-0056`
Den doc: `goblinbench/kimi-code-glm52-relevant-benchmark-20260616`

## Smoke findings

- `kimi-code` routes to upstream `kimi-k2.7-code` and still requires `temperature: 1.0`; `temperature: 0.2` returns HTTP 400.
- `glm52` routes to upstream `glm-5.2`. It can spend the first 64 tokens on `reasoning_content`; use generous `max_tokens` (campaign used 8192). `temperature: 0.2` with `max_tokens=512+` smokes successfully.

## Results snapshot

| Suite | Kimi Code fixed rerun | GLM52 |
|---|---:|---:|
| coding, 6-scenario subset | 5/6, avg .833, 1 runner fail | 4/6, avg .844, 2 runner fails |
| mcp-tools | 7/8, avg .869 | 8/8, avg .944 |
| mcp-tools-hard | 2/3, avg .867 | 1/3, avg .817 |
| fake-den-mcp | 1/1 | 1/1 |
| tool-call-behavior | 4/4 | 4/4 |
| den-mcp-ambiguity baseline | 2/6, avg .567 | 3/6, avg .500 |
| den-mcp-ambiguity hinted | 3/6, avg .846 | 3/6, avg .867 |
| mcp-session | 1/1 | 1/1 |
| orchestrator | 8/8 | 8/8 |
| autonomy-calibration | 3/3 | 3/3 |
| evidence-grounding | 3/3 | 3/3 |

## Notes

- Kimi Code hosting/runtime looked fixed vs 2026-06-13: no provider 429s, coding improved from 2/6 with 5 runner failures to 5/6 with 1 runner failure.
- Kimi Code still has mixed Den MCP ambiguity/tool-discipline behavior.
- GLM52 is a strong all-rounder; formal coding 4/6, but targeted retry made `coding.kth-selection` pass, so adjusted coding capability looks like 5/6 except `expression-evaluator`.
