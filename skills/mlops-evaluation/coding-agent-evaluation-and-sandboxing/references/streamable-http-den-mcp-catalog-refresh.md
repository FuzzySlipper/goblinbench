# Streamable HTTP Den MCP Catalog Refresh

Use this when a benchmark needs the live Den MCP tool schema catalog as fixture input without loading every Den MCP tool into the model context.

## Problem

GoblinBench fake-MCP suites sometimes need the complete current Den tool forest, but broadening a Hermes profile/toolset just to inspect schemas wastes prompt/schema budget and changes the thing being evaluated.

## Pattern

Query the canonical Den MCP streamable HTTP facade directly via JSON-RPC and store the result as a pinned fixture/catalog artifact.

Canonical endpoint used in GoblinBench work:

```text
http://192.168.1.10:5199/mcp
```

Protocol flow:

1. POST `initialize` to `/mcp` with headers:
   - `Accept: application/json, text/event-stream`
   - `Content-Type: application/json`
2. Read `Mcp-Session-Id` from the initialize response headers.
3. POST `tools/list` with the same `Mcp-Session-Id` header.
4. Parse either normal JSON or SSE `data:` JSON from `text/event-stream` responses.
5. Sort tools by name before writing the fixture so diffs are deterministic.
6. Preserve endpoint, protocol version, server info, generation timestamp, and tool count in the catalog metadata.

## Hermes-facing name transform

The base Den Core MCP endpoint may expose raw tool names such as `get_task`, while Hermes-loaded tools appear as `mcp_den_get_task`. If the eval needs Hermes-facing names, apply the deterministic prefix transform in the generator (for example `--name-prefix mcp_den_`) rather than loading all tools into Hermes.

Apply include/exclude filters **after** prefixing, so `--include-regex '^mcp_den_'` works for both already-prefixed and raw server names.

## GoblinBench command shape

```bash
python3 scripts/generate-fake-den-mcp-catalog.py \
  --mcp-url http://192.168.1.10:5199/mcp \
  --name-prefix mcp_den_ \
  --include-regex '^mcp_den_' \
  --catalog-output fixtures/fake-den-mcp/den-mcp-tools.live.json \
  --mcp-timeout-seconds 20
```

Then validate:

```bash
dotnet test tests/GoblinBench.Core.Tests/GoblinBench.Core.Tests.csproj --no-restore --filter FakeDenMcpGeneratorTests
dotnet run --project src/GoblinBench.Runner -- --suite fake-den-mcp --candidate fake-mcp-scripted
dotnet test --no-restore
```

## Observed live catalog metadata from 2026-06-08

- Tool count: `129`
- Protocol version: `2024-11-05`
- Server info: `DenCore.Service 0.1.0.0`
- Deterministic first/last prefixed tool names: `mcp_den_abort_worker_run` / `mcp_den_validate_topic_tags`

Treat these as sanity checks, not permanent constants; the live tool count will change as Den evolves.

## Pitfalls

- A plain GET can return `406 Not Acceptable`; this is not a failure of the endpoint, just the wrong MCP request shape.
- Do not call `tools/call` during catalog refresh. This pattern is schema-only.
- Do not record transient endpoint outages as durable tool failures. The reusable lesson is the protocol flow and fixture-pin pattern.
