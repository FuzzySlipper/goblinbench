# Den MCP Ambiguity Suite

`den-mcp-ambiguity` is a GoblinBench real-model fake-MCP suite for messy Den/Hermes tool-selection requests.

The suite uses the pinned live Den MCP schema catalog at `fixtures/fake-den-mcp/den-mcp-tools.live.json`, but every tool handler is fake and scenario-owned. Runs must not contact a live Den Core service except when refreshing the schema catalog with the explicit catalog generator.

## What it tests

The suite focuses on natural-language ambiguity that ordinary agents hit when a user mixes Den project ids, agents/personas, Discord-ish channel phrases, and document/task operations.

Initial scenarios:

- `den-mcp-ambiguity.den-mcp-doc-system-planner` — named regression for “put this report into a den-mcp doc” plus “discuss it with the den system planner”. Expected: store in project `den-mcp`, then leave planner-visible discussion/message evidence. Do not invent `den-system`.
- `den-mcp-ambiguity.project-explicit-report-doc` — explicit GoblinBench project routing for a new document.
- `den-mcp-ambiguity.persona-not-project-task-message` — `planner` is a routing/persona word, not a project id; read task #2086 and post to the `den-mcp` task thread.
- `den-mcp-ambiguity.search-vs-get-document` — fuzzy document title should use search, then get exact document.
- `den-mcp-ambiguity.comment-vs-update-document` — discussion/comment request should use `comment_on_document`, not overwrite the doc body.
- `den-mcp-ambiguity.clarify-destructive-doc-action` — ambiguous destructive “archive or maybe note” request should ask for clarification and perform no writes.

## Regeneration

Regenerate baseline scenario JSON from the pinned catalog:

```bash
python3 scripts/generate-den-mcp-ambiguity-suite.py --variant baseline
```

Regenerate the hinted-tool variant for A/B runs:

```bash
python3 scripts/generate-den-mcp-ambiguity-suite.py --variant hinted
```

The hinted variant writes the parallel suite `den-mcp-ambiguity-hinted`. It keeps the same prompts, fake tool results, expected calls, and scoring thresholds, but appends `TOOL HINT:` guidance to selected tool descriptions and `project_id` schema fields. The purpose is to measure whether a model can exploit clearer tool affordances for Den routing and clarification, not to make the task semantically different.

Refresh the live Den MCP catalog first only when intentionally updating the tool schema fixture:

```bash
python3 scripts/generate-fake-den-mcp-catalog.py \
  --mcp-url http://192.168.1.10:5199/mcp \
  --name-prefix mcp_den_ \
  --include-regex '^mcp_den_' \
  --catalog-output fixtures/fake-den-mcp/den-mcp-tools.live.json
```

## Scoring dimensions

The suite uses `mcp-tool-use` plus latency. The scorer now records:

- expected tool-call matches,
- stricter direct-argument grounding for fields such as `project_id`,
- forbidden tool use,
- forbidden argument values for hallucinated project/persona routing (`den-system`, `planner`, `runner`, etc.),
- clarification required/disallowed detection,
- fake artifact marker evidence,
- final-response grounding.

Important scorer behavior: if an expected argument key exists directly in the tool arguments, the scorer compares that field value. This prevents a wrong `project_id: "_global"` call from passing merely because the document `content` or final answer mentions `GoblinBench`.

## Run commands

Deterministic harness sanity:

```bash
dotnet test tests/GoblinBench.Core.Tests/GoblinBench.Core.Tests.csproj --no-restore --filter "FakeDenMcpGeneratorTests|McpToolBehaviorSuiteTests"
dotnet run --no-restore --project src/GoblinBench.Runner -- --suite den-mcp-ambiguity --candidate fake-mcp-scripted
```

Real-model A/B comparison example:

```bash
dotnet run --no-restore --project src/GoblinBench.Runner -- --suite den-mcp-ambiguity --candidate qwen3-35b-local-mcp-tools
dotnet run --no-restore --project src/GoblinBench.Runner -- --suite den-mcp-ambiguity-hinted --candidate qwen3-35b-local-mcp-tools
dotnet run --no-restore --project src/GoblinBench.Runner -- --suite den-mcp-ambiguity --candidate den-router-deepseek-flash-tool-behavior
dotnet run --no-restore --project src/GoblinBench.Runner -- --suite den-mcp-ambiguity-hinted --candidate den-router-deepseek-flash-tool-behavior
```

Generate a combined report:

```bash
mkdir -p runs/den-mcp-ambiguity-report
dotnet run --no-restore --project src/GoblinBench.Runner -- report \
  RUN_ID_SCRIPTED RUN_ID_QWEN RUN_ID_DEEPSEEK \
  --suite den-mcp-ambiguity \
  --output runs/den-mcp-ambiguity-report/report.md
```

## First checked run

Run ids from the initial implementation check:

- scripted sanity: `run-20260608-130157-35d82b35` — 6/6 pass
- Qwen3.6-35B local fake MCP tools: `run-20260608-130206-45f1ad30` — 2/6 pass under stricter routing scoring
- den-router DeepSeek Flash fake MCP tools: `run-20260608-130358-37210e19` — 1/6 pass under stricter routing scoring

Combined report:

- Markdown: `runs/den-mcp-ambiguity-report/report.md`
- JSON: `runs/den-mcp-ambiguity-report/report.json`

To browse and compare runs interactively, use the live viewer instead of a static export:

```bash
dotnet run --project src/GoblinBench.Runner -- report serve
# then open the printed LAN/localhost URL
```

Early behavior signal: both real candidates often choose plausible Den tools, but both over-act on the destructive archive-vs-note case and both drift to `_global`/wrong-project routing in document creation/search cases. The named `den-mcp doc` + `den system planner` regression remains discriminating: models can match the rough tool shape while still treating planner/system wording as project-routing evidence.
