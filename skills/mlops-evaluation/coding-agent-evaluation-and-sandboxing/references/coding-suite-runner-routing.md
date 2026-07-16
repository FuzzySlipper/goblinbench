# Coding suite runner routing

## Runner selection order (Program.cs)

The runner tries candidates against runners in this order:

1. `ScriptedCandidateRunner` — `cli_command == "coding-scripted"`
2. `FakeMcpCandidateRunner`
3. `FakeFuzzyCandidateRunner`
4. `OpenAiMcpToolUseRunner`
5. `OpenAiFuzzyAgentRunner`
6. `OpenAiMcpSessionRunner`
7. `CodingCandidateRunner` — `cli_command == "coding-scripted"`
8. `CodingAgentRunner` — `kind == CandidateKind.CodingAgent`
9. `ElectronCandidateRunner`
10. `VisionCandidateRunner`
11. `NoOpCandidateRunner` — matches any `Kind=Unknown`
12. `OpenAiChatRunner` — any `OpenAiModel`
13. `HermesProfileRunner`
14. `ServiceEndpointRunner`
15. `ExternalCliRunner`

## Implication for den-router chat candidates

Plain den-router candidates use:
- `kind: "OpenAiModel"`
- `cli_command: "mcp-openai-tool-use"` (for MCP suites) or no `cli_command`

These hit runner #4 (`OpenAiMcpToolUseRunner`) for MCP suites, or #12 (`OpenAiChatRunner`) for plain chat. **Neither can execute code in a disposable workspace**, so the coding scorer has nothing to test. The runner silently SKIPs these candidates for coding scenarios.

Confirmed 2026-06-11: `demo-noop` ran `coding.retry-policy` successfully because it matches `coding-scripted`. Den-router chat candidates (`den-router-stepfun-tool-behavior`, etc.) were not present in any coding scenario artifact dirs.

## Workarounds

1. **pi + den-router extension** — build a pi extension that routes tool calls through `127.0.0.1:18082`, then create a `CodingAgent` candidate pointing at pi with that extension. Same pattern as `lemonade-pi-extension.js`.
2. **pi with `--provider den-router`** — if pi supports a `den-router` provider alias, configure it via `models.json` with `baseUrl: "http://127.0.0.1:18082/v1"` and the target model name.
3. **Dedicated coding runner** — implement a runner that wraps chat models in a code-execution loop (not yet built).
