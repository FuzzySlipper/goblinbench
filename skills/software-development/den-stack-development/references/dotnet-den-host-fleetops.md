# Den Host FleetOps — concrete example

This reference documents the FleetOps API implementation added to Den Host
(task #1947), as a concrete example of the `dotnet-worker-http-api` pattern.

## Source layout

```
src/DenHost/FleetOps/
├── FleetOpsModels.cs          — CamelCase JSON DTOs (overview, actions, runs)
├── FleetOpsActionRegistry.cs  — Declarative allowlist of 9 actions (5 runnable, 4 disabled)
├── FleetOpsServiceUnitDiscovery.cs — systemctl --user list-units for hermes-gateway@*
├── FleetOpsCommandExecutor.cs — Process wrapper with timeout, redaction
├── FleetOpsRunStore.cs        — Thread-safe in-memory bounded store (LRU eviction)
├── FleetOpsSecretRedactor.cs  — Regex-based secret redaction (tokens, keys, passwords)
├── FleetOpsService.cs         — Orchestration: validate, confirm, build cmd, execute, track
├── FleetOpsOptions.cs         — Config section (ListenAddress, SystemctlPath, etc.)
├── FleetOpsHostedService.cs   — IHostedService running WebApplication Kestrel host
```

## Key classes

### FleetOpsHostedService (the HTTP host)

- Takes `FleetOpsService`, `IOptions<FleetOpsOptions>`, `ILogger` from parent DI
- Creates inner `WebApplication` with `UseKestrel()` + `UseUrls(options.ListenAddress)`
- Maps routes via closure capture of `_fleetOps`:
  - `GET /api/host/fleet-ops` → `_fleetOps.GetOverviewAsync()`
  - `POST /api/host/fleet-ops/actions/{actionId}/runs` → `_fleetOps.ExecuteActionAsync()`
  - `GET /api/host/fleet-ops/runs/{runId}` → `_fleetOps.GetRun()`
  - `GET /healthz` → static healthy response

### FleetOpsActionRegistry

Declarative action definitions with:
- `fleet-status` — non-mutating, runs `restart-agent-services` script
- `fleet-smoke` — non-mutating, runs `smoke-hermes-fleet.sh`
- `restart-all` — mutating, needs confirmation, high risk
- `restart-failed` — mutating, medium risk
- `restart-profile` — mutating, systemctl template `restart hermes-gateway@{profile}.service`
- 4 additional disabled-in-placeholder actions

### FleetOpsService execute flow

1. Resolve action from registry
2. Check disabled
3. Validate args against schema + reject unknown args
4. Check confirmation for mutating actions
5. For restart-profile: validate profile is a discovered service unit
6. Build command (systemctl template or script path)
7. Create run record, mark started
8. Execute with timeout
9. Update run with exit code, stdout/stderr, status

## DI registration

```csharp
// Options
services.AddOptions<FleetOpsOptions>()
    .Bind(configuration.GetSection(FleetOpsOptions.SectionName));
// IMPORTANT: concrete singleton needed because services take FleetOpsOptions directly
services.AddSingleton(sp => sp.GetRequiredService<IOptions<FleetOpsOptions>>().Value);

// Services
services.AddSingleton<FleetOpsActionRegistry>();
services.AddSingleton<IFleetOpsServiceUnitDiscovery, SystemdFleetOpsDiscovery>();
services.AddSingleton<IFleetOpsCommandExecutor, ProcessFleetOpsCommandExecutor>();
services.AddSingleton<IFleetOpsRunStore, InMemoryFleetOpsRunStore>();
services.AddSingleton<FleetOpsService>();
services.AddHostedService<FleetOpsHostedService>();
```

## Config section (den-host.json)

```json
{
  "FleetOps": {
    "Enabled": true,
    "ListenAddress": "http://0.0.0.0:5400",
    "ScriptsDirectory": "/home/agents/local/hermes-fleet/bin",
    "SystemctlPath": "systemctl"
  }
}
```

## Smoke validation

```bash
# Health
curl http://localhost:5400/healthz
# → {"status":"healthy","service":"den-host"}

# Overview (lists all actions + discovered service units)
curl http://localhost:5400/api/host/fleet-ops

# Dry-run an action
curl -X POST http://localhost:5400/api/host/fleet-ops/actions/fleet-status/runs \
  -H "Content-Type: application/json" \
  -d '{"actionId":"fleet-status","dryRun":true}'

# Run lookup (use runId from response)
curl http://localhost:5400/api/host/fleet-ops/runs/{runId}
```
