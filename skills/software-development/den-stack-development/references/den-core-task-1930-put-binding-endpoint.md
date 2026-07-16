# Task #1930: PUT binding registration — error sequence

## What was built
`PUT /api/direct-delivery/bindings/{instanceId}` — binding registration/heartbeat endpoint in `DirectDeliveryContractRoutes.cs`. Den-host sends `AdapterBindingRequest` and expects `AdapterBindingSnapshot` (camelCase) response.

## Error sequence

### 1. 400 BadRequest, empty body
**Cause:** Route param `{adapterInstanceId}` collided with DTO property `AdapterInstanceId`. ASP.NET Core minimal API binding got confused between route binding and body binding.

**Fix:** Renamed route param to `{instanceId}`. Validated URL == body match manually.

### 2. Another 400 BadRequest, empty body
**Cause:** Request body serialized with camelCase (`JsonSerializerDefaults.Web`), but the server uses `SnakeCaseLower` globally. So `adapterKind` in the JSON didn't match `AdapterKind` on the DTO.

**Fix:** Serialize request bodies with snake_case (`JsonOpts` with `SnakeCaseLower`).

### 3. Tests expecting wrong JSON field names
**Cause:** The PUT endpoint inherits the server's snake_case serialization. Test assertions checked for camelCase property names.

**Fix (first attempt):** Updated test assertions to snake_case. Then realized den-host expects camelCase.

### 4. Overrode response to camelCase, tests broke again
**Cause:** Changed route to return camelCase (`Results.Json(response, camelOptions)`). Tests were now expecting snake_case.

**Resolution:** Use `Results.Json(response, camelOptions)` for the PUT response (den-host compat). Test assertions use camelCase property names. Request bodies always use snake_case (server default).

### 5. Re-registration test: timestamps equal
**Cause:** `datetime('now')` in SQLite has second precision. `Task.Delay(10)` was far too short.

**Fix:** `await Task.Delay(1100)`.

### 6. xUnit analyzer error: `Assert.NotNull` on `JsonElement`
**Cause:** `JsonElement` is a struct (value type), not a reference type.

**Fix:** Use `Assert.NotEqual(default, variable)`.

## Key insight
The server has TWO serialization contexts:
- **Request deserialization** (inbound): snake_case from `ConfigureHttpJsonOptions`
- **Response serialization** (outbound): snake_case by default, but `Results.Json(dto, customOptions)` can override per-endpoint

When adding an endpoint consumed by an external client (den-host, gateway, etc.), check what JSON convention the client expects and override if needed.
