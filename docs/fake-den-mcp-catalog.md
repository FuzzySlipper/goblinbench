# Fake Den MCP Catalog Generator

GoblinBench can evaluate Den MCP-style tool use without touching the real Den server by turning a captured `tools/list` schema into a fake-MCP tool forest.

## What this gives us

- A generated catalog of Den MCP tool schemas in GoblinBench fake-MCP format.
- Optional generated scenarios that embed the whole tool forest into `input.fake_mcp.tools`.
- Canned, side-effect-free tool results for every tool.
- Variant support for experiments with tool descriptions and side-effect/error return policy.
- A refresh path that can be run periodically as Den MCP adds/removes/renames tools.

The fake catalog is **schema-only**. The fake handlers never call Den Core or a real MCP server.

## Script

```bash
python scripts/generate-fake-den-mcp-catalog.py \
  --input tests/fixtures/den-mcp-tools-list.sample.json \
  --include-regex '^mcp_den_' \
  --catalog-output fixtures/fake-den-mcp/den-mcp-tools.generated.json \
  --scenario-output suites/fake-den-mcp/all-den-tools.generated.json \
  --scenario-id fake-den-mcp.all-den-tools \
  --prompt 'Use fake Den MCP tools to read task 2085; do not mutate anything.' \
  --expected-tool mcp_den_get_task \
  --expected-arg task_id=2085
```

For live refresh from the canonical streamable HTTP Den MCP facade, use `--mcp-url` and prefix raw Den Core tool names into the Hermes-facing `mcp_den_...` shape:

```bash
python scripts/generate-fake-den-mcp-catalog.py \
  --mcp-url http://192.168.1.10:5199/mcp \
  --name-prefix mcp_den_ \
  --include-regex '^mcp_den_' \
  --catalog-output fixtures/fake-den-mcp/den-mcp-tools.live.json
```

`--mcp-url` sends MCP protocol `initialize` and `tools/list` over streamable HTTP with `Accept: application/json, text/event-stream`; it does not invoke any Den tool. The pinned live catalog currently lives at `fixtures/fake-den-mcp/den-mcp-tools.live.json` and records the endpoint, server info, protocol version, generation timestamp, and tool count.

For live refresh from a stdio MCP server, use `--mcp-command` instead of `--input` or `--mcp-url`:

```bash
python scripts/generate-fake-den-mcp-catalog.py \
  --mcp-command 'YOUR_DEN_MCP_STDIO_COMMAND_HERE' \
  --name-prefix mcp_den_ \
  --include-regex '^mcp_den_' \
  --catalog-output fixtures/fake-den-mcp/den-mcp-tools.generated.json \
  --scenario-output suites/fake-den-mcp/all-den-tools.generated.json \
  --scenario-id fake-den-mcp.all-den-tools
```

`--mcp-command` only sends MCP protocol `initialize` and `tools/list`; it does not invoke any Den tool.

## Description/error variants

To test whether clearer tool descriptions improve model behavior, provide an override map:

```json
{
  "mcp_den_update_task": {
    "description": "Write-like task update tool. Do not use for read-only inspection. Requires blocker fields when status=blocked."
  },
  "mcp_den_get_task": "Read-only task detail lookup. Use this when the user asks about one known task id."
}
```

Then run:

```bash
python scripts/generate-fake-den-mcp-catalog.py \
  --input captured-tools-list.json \
  --description-overrides overrides/clearer-den-descriptions.json \
  --variant-name clearer-descriptions \
  --catalog-output fixtures/fake-den-mcp/den-mcp-tools.clearer.generated.json \
  --scenario-output suites/fake-den-mcp/all-den-tools.clearer.generated.json
```

For fake side-effect-like tools, choose the return policy:

- `--side-effect-policy guided-error` (default): write-like tools return a clear fake error and `use_suggestion` telling the model not to claim real state changed.
- `--side-effect-policy noop`: write-like tools return `ok: true` but explicitly say it was a no-op.
- `--side-effect-policy ok`: all tools return a generic fake ok/read result.

This lets us compare whether guided fake errors reduce hallucinated completion or improve recovery.

## Static smoke scenario

`/suites/fake-den-mcp/task-read-vs-update.json` is a hand-authored small Den-shaped forest. It asks the model to inspect task `2085` using `mcp_den_get_task` while avoiding write-like tools such as `mcp_den_update_task`, `mcp_den_send_message`, and `mcp_den_store_document`.

Run deterministic validation:

```bash
dotnet run -- --suite fake-den-mcp --candidate fake-mcp-scripted
```

Run a real OpenAI-compatible tool-calling candidate the same way as other fake-MCP suites, for example a den-router candidate using `runner: mcp-openai-tool-use`.

## Periodic refresh idea

A cron/job can run the generator against the real Den MCP HTTP facade and then run:

```bash
dotnet test --no-restore --filter FakeDenMcpGeneratorTests
dotnet run -- --suite fake-den-mcp --candidate fake-mcp-scripted
```

If the generated catalog diff is large, inspect it before committing. The important regression signal is not only added/removed tools; description/schema wording changes can change model routing behavior.
