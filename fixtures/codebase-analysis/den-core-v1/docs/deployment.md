# DenCore v1 — Deployment Guide

## Prerequisites

- .NET 8 SDK
- SQLite 3 (runtime dependency, auto-created)
- Optional: LLM endpoint for librarian features

## Build

```bash
cd repo
dotnet restore
dotnet build -c Release
```

## Configuration

Configuration is read from `appsettings.json` and environment variables. Key settings:

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `ConnectionStrings:DefaultConnection` | `CONNECTIONSTRINGS__DEFAULTCONNECTION` | `Data Source=dencore.db` | SQLite connection string |
| LLM endpoint (hardcoded) | — | `http://192.168.1.10:8080` | OpenAI-compatible API base URL |
| `ASPNETCORE_URLS` | `ASPNETCORE_URLS` | `http://localhost:5000` | Kestrel listen URLs |

> **Note**: The LLM endpoint is currently hardcoded in `Program.cs` (line 30).
> Change `192.168.1.10` to your LLM host before deploying to production.
> This should be externalized to configuration in a future release.

## Run

```bash
cd repo/src/DenCore.Service
dotnet run -c Release
```

Or as a published deployment:

```bash
dotnet publish -c Release -o ./publish
cd publish
./DenCore.Service
```

## Health Check

```
GET http://localhost:5000/health
```

Expected response: `{"status":"OK","timestamp":"..."}`

## Database

The SQLite database file is created automatically at startup in the working directory.
To reset, delete the `dencore.db` file and restart the service.

## Logging

Structured logging via `ILogger<T>`. Configure log levels in `appsettings.json`.
Default level: Information.

## Known Limitations (v1)

1. Single-node only — no horizontal scaling
2. In-memory caches do not persist across restarts
3. LLM endpoint IP is hardcoded (see Configuration note above)
4. No authentication/authorization
5. Health endpoint does not verify database connectivity
6. Background dispatch loop has no health signal

## Deprecation Notes

- The `/api/items/{id}` compat route is kept alongside `/api/tasks/{id}` and will be removed in v2.
- `McpToolProfile` field on `ProjectTask` model is deprecated in favor of `McpToolProfileRegistry`.
- `LegacySenderId` on `Message` is kept for wire-format compatibility.
