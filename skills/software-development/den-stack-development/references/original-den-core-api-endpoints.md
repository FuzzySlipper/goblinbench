---
name: den-core-api-endpoints
description: Add, test, and debug REST API endpoints in Den Core — minimal API route registration, request/response DTOs, JSON serialization conventions, model binding pitfalls, and integration testing patterns.
---

# Den Core API Endpoints

How to add a new REST API endpoint to Den Core and write integration tests for it.

## Trigger conditions

- You need to add a new HTTP route to `den-core` (GET/POST/PUT/DELETE).
- You're fixing a 400/405/500 on an existing route.
- You're writing integration tests for a Core API endpoint.

## Route registration

All routes are registered in `src/DenCore.Service/Program.cs` via extension methods like `app.MapDirectDeliveryContractRoutes()`. Route definitions live in `src/DenCore.Service/Routes/`.

Pattern:

```csharp
// In your routes file
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

## JSON serialization (critical gotcha)

Den Core configures **`SnakeCaseLower`** globally in `Program.cs` line 67-72:

```csharp
builder.Services.ConfigureHttpJsonOptions(o =>
{
    o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower;
    o.SerializerOptions.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower));
    o.SerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
});
```

### Implications

- **Request bodies must use snake_case** — `adapter_kind` not `adapterKind`
- **Response bodies use snake_case** by default — `adapter_instance_id` not `adapterInstanceId`
- **PropertyNameCaseInsensitive** is NOT set on the server side, but it IS the default on most client `JsonSerializerOptions`, so single-word properties (`host`, `status`) work across conventions

### Per-endpoint serialization override

When a client expects camelCase (e.g. den-host's `AdapterBindingSnapshot` deserializer using `JsonSerializerDefaults.Web`), use `Results.Json()` with custom options:

```csharp
var camelOptions = new JsonSerializerOptions(JsonSerializerDefaults.Web);
return Results.Json(response, camelOptions);
```

## Route parameter vs DTO property name collision (critical gotcha)

If a route parameter name overlaps with a property name on your body DTO, ASP.NET Core's model binding gets confused and returns **400 BadRequest with empty body**.

**BAD** — route param `{adapterInstanceId}` collides with DTO's `AdapterInstanceId`:
```csharp
// Route: /bindings/{adapterInstanceId}
group.MapPut("/bindings/{adapterInstanceId}", async (
    string adapterInstanceId,                              // ← collides with
    DirectDeliveryBindingRegistration request, ...) => {}  // ← request.AdapterInstanceId
```

**GOOD** — rename route param to avoid collision:
```csharp
// Route: /bindings/{instanceId}
group.MapPut("/bindings/{instanceId}", async (
    string instanceId,
    DirectDeliveryBindingRegistration request, ...) => {}
```

Then validate URL == body match manually:
```csharp
if (!string.Equals(instanceId, request.AdapterInstanceId, StringComparison.Ordinal))
    return Results.BadRequest(new { error = "URL instanceId must match body adapterInstanceId." });
```

## Request validation

Do validation in the handler body, not with data annotations. Use explicit `Results.BadRequest()`:

```csharp
if (string.IsNullOrWhiteSpace(request.RequiredField))
    return Results.BadRequest(new { error = "requiredField is required." });
```

## Integration test pattern

Tests live in `tests/DenCore.Service.Tests/` and use the `WebApplicationFactory<Program>` pattern.

### Setup

```csharp
public sealed class MyApiTests : IAsyncLifetime
{
    private const string ProjectId = "test-proj";
    
    // Snake_case for request body serialization (matches server)
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) }
    };
    
    // CamelCase for endpoints that override serialization
    private static readonly JsonSerializerOptions JsonCamelOpts = new(JsonSerializerDefaults.Web);

    private MyAppFactory _factory = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _factory = new MyAppFactory();
        var initializer = new DatabaseInitializer(_factory.DatabasePath, NullLogger<DatabaseInitializer>.Instance);
        await initializer.InitializeAsync();
        _client = _factory.CreateClient();
        
        // Seed project if needed
        using var scope = _factory.Services.CreateScope();
        var projects = scope.ServiceProvider.GetRequiredService<IProjectRepository>();
        await projects.CreateAsync(new Project { Id = ProjectId, Name = "Test Project" });
    }

    public Task DisposeAsync()
    {
        _client.Dispose();
        _factory.Dispose();
        return Task.CompletedTask;
    }
}
```

### Sending requests

- Use `JsonOpts` (snake_case) when the server will deserialize via its global snake_case config.
- Use `JsonCamelOpts` only when the endpoint specifically uses `Results.Json(response, camelOptions)`.

**Prefer concrete DTOs over anonymous types** for request bodies — they give compile-time safety and avoid property-name duplication:

```csharp
// GOOD: concrete DTO from DenCore.Models — property names defined once
var registration = new DirectDeliveryBindingRegistration
{
    AdapterKind = "host",
    AdapterInstanceId = "test-1",
    Host = "ci-check",
    ManagedRoles = ["coder", "reviewer"],
};

var json = JsonSerializer.Serialize(registration, JsonOpts);
var content = new StringContent(json, Encoding.UTF8, "application/json");
var response = await _client.PutAsync("/api/direct-delivery/bindings/test-1", content);
```

Avoid anonymous types for request bodies — the property names are duplicated and can drift from the DTO:

```csharp
// FRAGILE: anonymous type — property names duplicated from DTO
var body = new { adapter_kind = "host", ... };
```

### Seeding database state

Use scoped DI to get repositories and seed data:

```csharp
using var scope = _factory.Services.CreateScope();
var repo = scope.ServiceProvider.GetRequiredService<IMyRepository>();
await repo.UpsertAsync(new MyEntity { ... });
```

### App factory (inline class)

```csharp
private sealed class MyAppFactory : WebApplicationFactory<Program>
{
    private readonly string _dbPath = Path.Combine(Path.GetTempPath(), $"den-core-{Guid.NewGuid()}.db");
    public string DatabasePath => _dbPath;

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        builder.ConfigureAppConfiguration((_, config) =>
        {
            config.AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["db-path"] = _dbPath,
                ["llm-endpoint"] = "http://localhost/fake",
                ["llm-api-key"] = "test-key",
                ["llm-model"] = "fake",
            });
        });
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<DbConnectionFactory>();
            services.AddSingleton(new DbConnectionFactory($"Data Source={_dbPath}"));
        });
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (File.Exists(_dbPath)) File.Delete(_dbPath);
    }
}
```

## Adding request/response DTOs

DTOs for contract endpoints live in `src/DenCore/Models/DirectDeliveryContract.cs` (or the appropriate contract file). Keep them in the `DenCore.Models` namespace so both the service project and test project can reference them.

Use `required` properties for mandatory fields:

```csharp
public sealed class MyRequestDto
{
    public required string FieldName { get; set; }
    public List<string> OptionalList { get; set; } = [];
}
```

## SQLite timestamp precision in tests

`datetime('now')` in SQLite has **second precision**. Tests that assert a timestamp changed after a re-registration need a delay >1 second:

```csharp
await Task.Delay(1100); // not 10ms!
```

## Live deployment

After the endpoint passes tests and is promoted to `main`, deploy to den-srv:

```bash
# 1. Push to GitHub canonical remote
git push origin main

# 2. Run the deploy script (builds, publishes, rsyncs to den-srv, restarts service, smoke-checks)
bash scripts/deploy-live-server.sh
```

The deploy script handles:
- `dotnet publish` with Release/linux-x64/self-contained
- Rsync to `/data/services/den-core/app` on den-srv
- systemd restart of `den-core.service`
- Smoke check against `/health` and the MCP loopback endpoint

If the deploy script's smoke check shows a **502 from the den-publish tunnel** (`http://192.168.1.10:18080/den-core-api/health`), that's typically the reverse proxy reconnecting after the restart — the MCP loopback smoke on `127.0.0.1:5299` is the authoritative health check.

**Live database FK constraints:** The live database has real data with foreign keys. For example, `agent_instance_bindings.project_id` references `projects.id`. Always pass a valid `projectId` that exists in the live database (check via `GET /api/projects` or query the DB). An empty or nonexistent project ID will cause a 500 with `SQLite Error 19: FOREIGN KEY constraint failed`.

## Pitfalls

- **Empty 400 response**: Usually means model binding failed before the route handler ran. Check for route param ↔ DTO property name collisions, or serialization convention mismatch.
- **`Assert.NotNull` on `JsonElement`**: `JsonElement` is a struct (value type). Use `Assert.NotEqual(default, variable)` instead.
- **Route ordering with similar patterns**: GET `/bindings` and PUT `/bindings/{id}` are fine with different HTTP methods.
- **`[FromBody]` attribute**: Not needed in minimal APIs — complex types are automatically bound from the body. Adding it can cause confusion when route params share names with DTO properties.
- **Readiness endpoint listing**: When adding new endpoints, update the readiness endpoint's `metadata.endpoints` array so it stays accurate.
