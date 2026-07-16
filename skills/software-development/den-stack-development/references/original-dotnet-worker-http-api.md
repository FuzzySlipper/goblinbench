---
name: dotnet-worker-http-api
description: >-
  Class-level pattern for adding HTTP API endpoints to a .NET Worker Service /
  Generic Host CLI binary. Covers SDK switch, FleetOps-style background Kestrel
  host, DI wiring, and pitfall prevention. NOT about building a full ASP.NET
  web app — this is the "I have a CLI/worker binary that needs a bounded HTTP
  API alongside its existing services" case.
trigger: >-
  When you need to expose an HTTP API from an existing .NET CLI / Worker Service
  binary. When someone says "add a FleetOps API to Den Host" or "add an HTTP
  endpoint to a Generic Host app". When a project uses
  Microsoft.NET.Sdk.Worker and you need an HTTP listener.
domain: .NET, C#, ASP.NET Core, Kestrel, Generic Host
---

# Adding HTTP API to .NET Worker Service

## Overview

When an existing .NET Worker Service or Generic Host CLI binary needs a
bounded HTTP API (e.g. FleetOps, health endpoints, admin surface), the
cleanest approach is:

1. Switch SDK to `Microsoft.NET.Sdk.Web` (the source of truth for Kestrel)
2. Add a `BackgroundService` / `IHostedService` that starts a minimal
   `WebApplication` for the API endpoints
3. Wire parent DI services into route handlers via constructor injection
   and closure capture
4. Keep the existing CLI/background-service behavior completely intact

## Step-by-step

### 1. SDK switch

If the project uses `Microsoft.NET.Sdk.Worker`:

```xml
<!-- BEFORE -->
<Project Sdk="Microsoft.NET.Sdk.Worker">
  ...
  <ItemGroup>
    <FrameworkReference Include="Microsoft.AspNetCore.App" />
  </ItemGroup>

<!-- AFTER -->
<Project Sdk="Microsoft.NET.Sdk.Web">
  ...
  <!-- No explicit FrameworkReference — Web SDK implies it -->
```

- `Microsoft.NET.Sdk.Web` brings in Kestrel, minimal API, routing, etc.
- Remove the explicit `<FrameworkReference>` — Web SDK provides it implicitly,
  and leaving a redundant one produces warning NETSDK1086.
- `OutputType` stays `Exe`. All existing `IHostedService` / background service
  behavior continues to work unchanged.

### 2. Create the hosted service

```csharp
public sealed class MyApiHostedService : IHostedService
{
    private readonly MyService _myService;
    private readonly MyOptions _options;
    private readonly ILogger<MyApiHostedService> _logger;
    private WebApplication? _app;

    public MyApiHostedService(
        MyService myService,
        IOptions<MyOptions> options,  // IOptions<T> for config binding
        ILogger<MyApiHostedService> logger)
    {
        _myService = myService;
        _options = options.Value;
        _logger = logger;
    }

    public async Task StartAsync(CancellationToken ct)
    {
        if (!_options.Enabled) { /* skip */ return; }

        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseKestrel();
        builder.WebHost.UseUrls(_options.ListenAddress);
        builder.Logging.ClearProviders();
        builder.Logging.AddConsole();

        _app = builder.Build();

        _app.MapGet("/healthz", () => Results.Ok(...));

        // Capture services via closures:
        _app.MapGet("/api/my-endpoint", async (CancellationToken ct) =>
        {
            var result = await _myService.DoSomethingAsync(ct);
            return Results.Ok(result);
        });

        await _app.StartAsync(ct);
    }

    public async Task StopAsync(CancellationToken ct)
    {
        if (_app is not null)
        {
            await _app.StopAsync(ct);
            await _app.DisposeAsync();
        }
    }
}
```

### 3. DI registration

Register in the existing `AddXxx()` extension method:

```csharp
// OPTIONS — two registrations needed:
services.AddOptions<MyOptions>()
    .Bind(configuration.GetSection(MyOptions.SectionName));
// Concrete singleton for services that take MyOptions (not IOptions<MyOptions>):
services.AddSingleton(sp => sp.GetRequiredService<IOptions<MyOptions>>().Value);

// SERVICES
services.AddSingleton<MyService>();
services.AddSingleton<MyActionRegistry>();
services.AddHostedService<MyApiHostedService>();
```

**Pitfall**: If your service's constructor takes `MyOptions` directly (not
`IOptions<MyOptions>`), you MUST register the concrete singleton too.
Omitting it causes: `Unable to resolve service for type 'MyOptions'`.

### 4. Config section

Add a config section for the API:

```json
{
  "MyApi": {
    "Enabled": true,
    "ListenAddress": "http://0.0.0.0:5400"
  }
}
```

## Pitfalls

- **PITFALL: SDK choice**. `UseKestrel()` and `UseUrls()` require the Web SDK.
  Worker SDK lacks these extensions even with FrameworkReference. Always switch
  to `Microsoft.NET.Sdk.Web` when adding HTTP.
- **PITFALL: FrameworkReference dupe**. The Web SDK provides
  `Microsoft.AspNetCore.App` implicitly. Leaving an explicit
  `<FrameworkReference>` produces NETSDK1086. Remove it.
- **PITFALL: Concrete Options vs IOptions\<T\>**. The `AddOptions<T>()` pattern
  registers `IOptions<T>`, not `T`. If your service takes `T` directly
  (common for options that are passed to ProcessStartInfo or similar), add
  `services.AddSingleton(sp => sp.GetRequiredService<IOptions<T>>().Value)`.
- **PITFALL: DI isolation**. The `WebApplication.CreateBuilder()` inside the
  hosted service creates a **separate DI container** from the parent Generic
  Host. The route handlers access parent services through closure capture
  (the fields of the hosted service class), NOT via DI constructor injection
  from the WebApplication. Do NOT register parent services in the inner
  WebApplication's DI — capture them.
- **PITFALL: Logging noise**. `.ClearProviders()` + `.AddConsole()` on the
  inner builder prevents doubled logging. The parent Generic Host already
  manages logging.
- **PITFALL: Config isolation**. The inner WebApplication does NOT read the
  parent's `den-host.json` config file automatically. API-level config
  (ListenAddress, Enabled) should live in the parent's config and be injected
  via `IOptions<T>` into the hosted service constructor.

## Verification

- `dotnet build` succeeds with 0 warnings
- Existing tests still pass (the SDK switch should NOT break existing tests)
- Start the app; `curl http://localhost:{port}/healthz` returns 200
- Smoke the API endpoints: overview, action execution, run lookup
- Verify existing CLI commands still work

## References

- `den-host` FleetOps implementation: references/den-host-fleetops.md
  Concrete example of this pattern in the Den stack.
