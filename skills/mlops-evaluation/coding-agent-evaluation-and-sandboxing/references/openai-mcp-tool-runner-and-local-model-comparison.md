# OpenAI-compatible fake-MCP tool runner and local model comparison

Use this note when extending GoblinBench-style fake MCP/tool-use eval suites or comparing local Lemonade models.

## Runner pattern

For a real-model fake-MCP runner that still stays deterministic/replayable:

1. Keep scenario-owned fake tools in `input.fake_mcp.tools` using OpenAI-compatible JSON schema fields (`name`, `description`, `input_schema`).
2. Build a `chat/completions` request with those tools mapped to OpenAI `tools: [{ type: "function", function: { name, description, parameters } }]`.
3. On each assistant tool call:
   - parse `tool_calls[*].function.name` and JSON string `arguments`;
   - execute against scenario canned `input.scripted_tool_calls` results, not real side effects;
   - append `role: "tool"`, `tool_call_id`, `name`, and JSON result content;
   - record a scorer artifact entry `{ tool, arguments, result, tool_call_id, order }`.
4. Stop when the assistant emits a normal content response or when a bounded `max_tool_rounds` is reached.
5. Write artifacts in the same shape as the deterministic runner:
   - `tool_calls.json`
   - `bypass_attempts.json`
   - `final_response.txt`
   - plus request/response round dumps and `chat_transcript.json` for debugging.

This lets `McpToolUseScorer` compare deterministic scripted runs and real OpenAI-compatible model tool runs without special cases.

## Important limitation

A pure `chat/completions` tool runner cannot observe real shell/Python/raw-HTTP bypass behavior, because the model only has the provided OpenAI tools. To test true bypass temptation, add a separate agent-mode runner that gives an agent both fake MCP tools and baseline tools such as shell/http, then records those attempts into `bypass_attempts.json`.

In the OpenAI-compatible runner, bypass-like behavior can only be tested by modeling tempting surfaces as fake tools, e.g. `http_raw_fetch` or `project_archive_sim`, and scoring them as forbidden tools.

## Lemonade local model comparison workflow

When comparing multiple local Lemonade models:

1. Query `/v1/models` and choose exact model IDs from Lemonade, because aliases/different quants can coexist.
2. Prefer the requested quant/checkpoint deliberately; duplicate names may differ only by capitalization or `builtin.` prefix.
3. Create a temporary candidates file rather than editing the canonical `candidates.json` for ad-hoc comparisons.
4. Run one suite with all comparison candidates so scenario ordering and harness version are identical.
5. Generate a report with `--den` so the model IDs, run ID, report path, and artifacts are durable.
6. Summarize both pass rate and failure mode; for tool suites, distinguish:
   - safe refusal after evidence collection;
   - safe refusal too early (skipped expected read-only evidence);
   - forbidden/decoy tool use;
   - tool thrashing before refusal;
   - correct tool calls but weak final grounding snippets.

## Observed signal from the mcp-tools suite

A representative local comparison on `mcp-tools` showed the suite is useful but still fairly easy for tool-calling-capable models:

- Gemma-4-26B-A4B-it Q4: 8/8, strongest overall, but not all perfect scores due to final snippet misses.
- Qwen3.6-35B Q8 and Qwen3.5-4B Q4: 7/8; smaller Qwen had a more serious forbidden decoy-tool failure.
- GLM-4.7-Flash Q4: 7/8; often safe-refused too early on HTTP temptation.
- Nemotron-3-Nano-30B Q4: 6/8; showed tool-thrashing before refusal on an impossible task.

Useful interpretation: the initial suite discriminates model/tool behavior, but many scenarios are direct enough that pass rates cluster high. To harden it, add more decoy tools with plausible outputs, multi-step stale/malformed branches where the wrong second call is tempting, stricter final grounding, and scenarios that require evidence gathering before refusal.
