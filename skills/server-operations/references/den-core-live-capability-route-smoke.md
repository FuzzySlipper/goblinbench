# Den Core live capability route smoke and recovery

Use this reference when a Den Core feature exists in the repo/tests but the live `/den-core-api` facade does not expose the expected API route, especially capability registry/invocation routes.

## Trigger symptoms

- `/den-core-api/health` is healthy but reports an older commit than the local/remote repo head.
- `/den-core-api/api/<new-route>` returns the static SPA HTML, `405 Method Not Allowed`, or otherwise behaves like a frontend fallback instead of the API route.
- Local tests for the route pass in the checkout, but production smoke cannot register/invoke through Core.

## Recovery pattern

1. **Confirm live/repo drift**
   - Check live health: `curl -fsS http://192.168.1.10:18080/den-core-api/health`.
   - Check the service source checkout on den-srv, commonly `/data/dev/den-core`.
   - Compare its `git rev-parse HEAD` against `origin/main` and the expected feature commit.

2. **Fast-forward the den-srv service checkout**
   - On den-srv: `cd /data/dev/den-core && git fetch origin main && git checkout main && git pull --ff-only origin main`.
   - Do not merge or force-push during service recovery; this is a deployment drift fix, not feature development.

3. **Run focused tests before live deploy**
   - For capability routes: `dotnet test tests/DenMcp.Server.Tests/DenMcp.Server.Tests.csproj --filter Capability --logger "console;verbosity=minimal"`.
   - Record pass counts in the Den task thread.

4. **Deploy with the owned runbook/script**
   - Use `/data/dev/den-core/scripts/deploy-live-server.sh --local` on den-srv.
   - Record the rollback backup path printed by the script, e.g. `/data/services/den-core/app.previous.<timestamp>`.
   - A transient `502` immediately after restart can occur while the service/proxy settles; retry health before declaring failure.

5. **Verify live route health and commit**
   - Re-run `/den-core-api/health` until it reports the expected commit.
   - Then smoke the new route through the same `/den-core-api/api/...` facade used by clients.

## Capability executor live-smoke pattern

For a prototype read-only executor such as `vision.analyze_image.v1`:

1. Start the temporary executor and verify both local and den-srv reachability (`/health`).
2. Register/update the capability through live Core `/den-core-api/api/capabilities/`.
3. Invoke through Core `/den-core-api/api/capabilities/{capabilityId}/invoke`.
4. Read back the invocation with `/den-core-api/api/capabilities/invocations/{invocationId}` and verify:
   - `status=completed`;
   - `output_summary` populated;
   - `model_provider` / `model_name` populated;
   - timing/cost metadata present as appropriate;
   - `output_json` parses and matches the capability schema.
5. If the executor was only temporary/unsupervised, immediately set the registry entry to `disabled` after smoke and include the invocation id in `metadata_json`. Do not leave live Core pointing at a process you are about to kill.
6. Stop the temporary executor and post the invocation handle plus rollback path to Den.

## Wire-format reminder

Den Core public REST routes use the configured snake_case JSON policy. Executor request/response envelopes sent by `CapabilityInvocationService` may use their own Core executor contract; verify the actual service DTO/client code rather than assuming the public REST casing also applies to the executor process.

## Evidence to post

- Source checkout before/after commit.
- Test command and pass count.
- Deploy command and rollback path.
- Live health response commit.
- Capability registration route and endpoint used.
- Invocation id and readback fields.
- Cleanup action for temporary executors (disabled registry entry and stopped process).
