---
name: den-stack-development
description: "Use when implementing, testing, deploying, or debugging Den stack changes across Den Core REST APIs, Den Web frontend/API contracts, Den Host/Worker HTTP APIs, Channels/Gateway integration, and live production verification."
version: 1.0.0
author: GoblinOverseer
license: MIT
metadata:
  hermes:
    tags: [den, den-core, den-web, den-host, dotnet, api, frontend, deployment]
    related_skills: [den-mcp, dogfood, requesting-code-review, systematic-debugging]
---

# Den Stack Development

This umbrella skill covers the class-level workflow for Den product and platform changes: Core REST endpoints, Web UI/API-contract fixes, Den Host / .NET worker HTTP APIs, Channels/Gateway integration surfaces, deployment, and live browser/API verification.

Use this instead of looking for one-session skills such as a single Den Web regression, a one-off Core binding endpoint, or a FleetOps HTTP API patch. Session-specific details live in `references/`; reusable starter files or probes should live under `templates/` or `scripts/`.

## When to Use

- Adding or debugging a Den Core REST endpoint, route registration, request/response DTO, or integration test.
- Fixing Den Web UI bugs, API-client normalization, document/task/channel screens, or production static deployment.
- Adding a bounded HTTP API to an existing .NET Worker Service / Generic Host binary such as Den Host.
- Investigating cross-layer Den failures where the symptom appears in Web but the cause may be Core, Channels, Gateway, den-host, or delivery adapters.
- Promoting reviewed Den changes to production and proving them with live smoke/browser evidence.

## Default Cross-Layer Workflow

1. **Start from Den as source of truth.** Read the task, workflow summary, relevant documents/messages, latest worker packets, review state, and live API evidence before editing code.
2. **Identify the real contract boundary.** Reproduce at the browser/UI, network payload, API client, server route, repository/storage, and delivery/adapter layer as appropriate. Do not patch the visible layer until you know which boundary violated the contract.
3. **Use an isolated worktree.** Prefer a task branch/worktree from the intended base (`origin/main` unless the task says otherwise). Avoid mixing unrelated local state into Den production changes.
4. **Patch narrowly but normalize defensively.** If a valid Den wire shape varies by null/omitted/case conventions, normalize at the API client or DTO boundary and keep components tolerant of legacy shape where practical.
5. **Add regression coverage for the observed wire shape.** Focused tests should fail on the stale assumption that caused the bug.
6. **Run targeted and broad validation.** Use the smallest test that proves the fix, then broader typecheck/build/integration tests when feasible.
7. **Review before promotion.** Record review round/verdict, branch/head/base commits, tests run, and unresolved findings before fast-forwarding/promoting.
8. **Deploy and live-smoke when user-facing or production behavior changes.** Preserve runtime config, restart services when required, run smoke scripts, and verify the real production UI/API.
9. **Post durable Den evidence.** Summarize root cause, files changed, tests, review, deployment target, smoke result, and live acceptance evidence in the task thread.

## Den Core REST API Endpoints

### Route registration

Routes are registered in `src/DenCore.Service/Program.cs` via extension methods like `app.MapDirectDeliveryContractRoutes()`. Route definitions live in `src/DenCore.Service/Routes/`.

```csharp
public static class SomeContractRoutes
{
    public static void MapSomeContractRoutes(this WebApplication app)
    {
        var group = app.MapGroup("/api/my-group");
        group.MapGet("/items", async (IRepo repo, string? filter) => { ... });
        group.MapPost("/items", async (MyRequestDto dto, IRepo repo) => { ... });
    }
}
```

Then add `app.MapSomeContractRoutes();` to `Program.cs`.

### Serialization conventions

Den Core configures `JsonNamingPolicy.SnakeCaseLower` globally. Request bodies must use snake_case (`adapter_kind`), responses are snake_case by default, and enums use snake_case. If a client expects camelCase, return `Results.Json(response, new JsonSerializerOptions(JsonSerializerDefaults.Web))` explicitly.

### Model-binding collision pitfall

A route parameter name that overlaps with a body DTO property can produce an empty 400 before the handler runs.

```csharp
// Prefer {instanceId}, not {adapterInstanceId}, when the DTO also has AdapterInstanceId.
group.MapPut("/bindings/{instanceId}", async (string instanceId, DirectDeliveryBindingRegistration request) =>
{
    if (!string.Equals(instanceId, request.AdapterInstanceId, StringComparison.Ordinal))
        return Results.BadRequest(new { error = "URL instanceId must match body adapterInstanceId." });
    ...
});
```

### Integration test pattern

Tests use `WebApplicationFactory<Program>`, test DB initialization, scoped repository seeding, and explicit JSON options. Prefer concrete DTOs over anonymous request bodies so DTO property names are defined once. Remember SQLite `datetime('now')` has second precision; timestamp-change assertions need a delay over one second.

See `references/den-core-task-1930-put-binding-endpoint.md` for a concrete binding endpoint example.

## Den Web Frontend and API Contracts

Use Den Web patterns for `/home/dev/den-web` or the mounted Den Web checkout: Vite/React UI rendering bugs, API-client shape mismatches, document/task/channel screens, production static deployment, and browser verification.

Common commands from the Den Web worktree:

```bash
npm test -- --run src/features/documents/DocumentDiscussion.test.ts
npx vitest run --reporter=verbose
npx tsc -b --noEmit
npm run build
```

### API shape pitfalls

- Nullable fields may be omitted instead of present as `null`; use nullish checks (`== null` / `!= null`) and client normalization where omitted and null are equivalent. See `references/den-web-document-discussion-comment-shape.md`.
- Channels worker-pool lobby payloads may need client normalization before rendering (`lobbyChannelId`, `totalMembers`, `byRole`, `members[].memberIdentity`, `status: "idle"`). See `references/den-web-worker-pool-lobby-shape-regression.md`.
- Direct Channels/session-policy UI must distinguish source channel metadata from concrete agent-instance/session-owner truth. See `references/den-web-direct-channels-and-session-policy-ui.md`.
- A Channels message write may not wake Hermes agents unless a direct-agent wake bridge is present. See `references/den-web-channel-human-message-agent-wake.md`.

### Local vs promoted/deployed fix pitfall

A regression can reappear when the correct patch exists only as uncommitted changes or on a stale task branch/worktree. Compare live build sentinel/deployed asset, `origin/main`, and local dirty worktrees before assuming a fix is already promoted.

## .NET Worker / Den Host HTTP APIs

When an existing .NET Worker Service or Generic Host CLI binary needs a bounded HTTP API, do not build a separate web app unless the product requires one. The usual pattern is:

1. Switch the project SDK from `Microsoft.NET.Sdk.Worker` to `Microsoft.NET.Sdk.Web`; remove redundant `FrameworkReference Include="Microsoft.AspNetCore.App"`.
2. Add an `IHostedService` / `BackgroundService` that starts a minimal `WebApplication` for the API endpoints.
3. Capture parent DI services in the hosted service and use route-handler closures; the inner `WebApplication.CreateBuilder()` has a separate DI container.
4. Register both `IOptions<T>` and concrete options singletons if services take `T` directly.
5. Preserve existing CLI/background behavior.

```csharp
public sealed class MyApiHostedService : IHostedService
{
    private readonly MyService _myService;
    private readonly MyOptions _options;
    private WebApplication? _app;

    public async Task StartAsync(CancellationToken ct)
    {
        if (!_options.Enabled) return;
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseKestrel();
        builder.WebHost.UseUrls(_options.ListenAddress);
        builder.Logging.ClearProviders();
        builder.Logging.AddConsole();
        _app = builder.Build();
        _app.MapGet("/healthz", () => Results.Ok(new { status = "ok" }));
        _app.MapGet("/api/overview", async (CancellationToken ct) => Results.Ok(await _myService.GetOverviewAsync(ct)));
        await _app.StartAsync(ct);
    }

    public async Task StopAsync(CancellationToken ct)
    {
        if (_app is not null) { await _app.StopAsync(ct); await _app.DisposeAsync(); }
    }
}
```

See `references/dotnet-den-host-fleetops.md` for the concrete Den Host FleetOps implementation.

## Deployment and Live Verification

- Push/promote to the canonical remote only after review gates are satisfied.
- Den Core deploys through the live server deploy script, publishes Release/linux-x64/self-contained, rsyncs to `/data/services/den-core/app`, restarts `den-core.service`, and smoke-checks `/health` and MCP loopback.
- A transient 502 from the den-publish tunnel after restart can be reverse-proxy reconnecting; loopback health is authoritative.
- Den Web static deploys must preserve runtime config such as `den-web-config.json`, update/check the build sentinel, restart the static service if required, run the smoke script, then browser-verify the user-visible acceptance criterion.
- Live Core DBs have real foreign keys; use project IDs that exist in production when testing write endpoints.

## Den MCP Transport and Tool Availability

The Den MCP endpoint can expose different tool sets depending on transport/profile, and not all tool names are available on a single transport in practice.

- **Transport-dependent tool exposure:** In this environment, `http://<host>:5199/mcp` without a profile exposes task tools (`create_task`, `list_tasks`, etc.) but rejects worker/assignment tools like `lease_worker` with `Unknown tool` errors. Adding `?tool_profile=runner` exposes worker/assignment tools, but tool calls can return `400 Bad Request`. Do not assume one transport URL exposes the full tool surface.
- **Check before scripting:** Before writing a script that calls multiple Den MCP tools, probe the target transport with `tools/list` to confirm the needed tool names are actually exposed. If the tool list differs from documentation, treat the live transport as authoritative and adapt the client/proxy strategy.
- **Composite client strategy:** When task tools and worker tools live on different transports, build a small multi-transport client rather than assuming a single session can reach everything. The script under `scripts/pi-crew-worker-matrix/` demonstrates a `McpClient` that can be instantiated per-transport.

## GoblinBench Live-Integration Scripts vs Runners

For live Den/pi-crew integration work where the substrate is unstable or under active development:

- **Prefer script form over runner form** when the task involves live external systems that may have transient bugs, schema drift, or transport quirks. A standalone Python/Node script under `scripts/` can be iterated, rerun, and adapted without rebuilding the .NET runner or registering new candidate kinds.
- **Reserve runner form** for stable, repeatable scenarios that fit the existing scenario/candidate/scorer model. When the live path is the thing being benchmarked rather than the candidate's behavior, the script form keeps the benchmark harness decoupled from substrate instability.
- **Always verify output paths.** A script defaulting to `runs/` must resolve from the repo root, not from the script's own directory. Use `Path(__file__).resolve().parents[N]` carefully; a one-off off-by-one in `parents[]` silently writes artifacts to `scripts/runs/` instead of `runs/`.

## Verification Checklist

- [ ] Den task/context/review state read before editing.
- [ ] Symptom reproduced at the right layer and contract boundary identified.
- [ ] Focused patch and regression coverage committed.
- [ ] Targeted tests and relevant broader tests/typecheck/build run, or blockers recorded.
- [ ] Review verdict recorded before promotion.
- [ ] Production deployment/smoke/browser/API verification completed when applicable.
- [ ] Den task/thread updated with root cause, evidence, and next state.
- [ ] MCP transport probed with `tools/list` before scripting multi-tool automation.
