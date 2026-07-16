# Static frontend service cutover on shared LAN hosts

Use this reference when moving a browser frontend out of an embedded backend app and deploying it as a standalone static service with reverse-proxy behavior.

## Recommended shape

- Build static assets in the source repo, then deploy only `dist/`/static output plus a small runtime config/sentinel to the server.
- Run a dedicated systemd service for the static frontend when no existing reverse proxy is the chosen owner.
- Put backend APIs on internal loopback or non-public ports and have the frontend service proxy explicit paths.
- Keep runtime configuration in a served JSON file (for example `/den-web-config.json`) so the static build can move between environments without rebuilding.
- Include a build sentinel (for example `/den-web-build.json`) with commit/build time/source so live smoke can prove which asset set is deployed.

## Node no-dependency static/reverse-proxy service checklist

For a small operational script, verify it:

- serves `STATIC_ROOT` and SPA fallback safely;
- prevents path traversal by resolving candidate paths under the resolved static root;
- has content types and sane cache headers;
- treats hashed asset names according to the bundler's actual hash alphabet (Vite hashes can be mixed-case/base64url, not only lowercase hex);
- preserves query strings when proxying backend requests;
- proxies each API namespace to its owning backend explicitly rather than relying on relative frontend paths;
- serves runtime config from file if present, otherwise from sanitized env/defaults;
- has a deterministic smoke script that exits nonzero on failed checks.

## Cutover sequence

1. Capture current service state and rollback handle before changes: active units, ports, app root, previous app directory, env files with secrets redacted.
2. Deploy the static build to a new service root and write runtime config/build sentinel. If the live static root is root-owned or otherwise not writable by the agent account, do not loosen ownership as an implicit side effect: stage assets into an agent-writable `/tmp/<deploy-id>` directory with `rsync`, then use `sudo rsync -a --delete`, `sudo install -m 0644` for config/sentinel/server files, and a service restart. Preserve a timestamped backup of the previous static root first.
3. Move the old backend service to an internal/non-public port if it formerly owned the public UI route.
4. Install/start the new static service on the public route.
5. Smoke from outside the host using the public URL: root HTML, assets, runtime config, build sentinel, backend API proxy endpoints, and representative app feature endpoints.
6. Browser-smoke the public root when useful to catch MIME/path/CORS issues that curl-only checks miss.
7. Record service names, ports, paths, smoke result, and rollback commands in Den/docs.
8. After the new service is stable, retire the old embedded UI path in the backend repo/service so stale assets cannot mask regressions.

## Evidence to report

- Public URL and service unit name.
- Internal backend URL/port after cutover.
- Static root path and build commit/sentinel.
- Smoke command and pass/fail count.
- If deploy required privileged copy into a root-owned static root: staging directory, exact `sudo rsync`/`install` actions, and confirmation that ownership/permissions were not broadened.
- Rollback directory/service backup.
- Den document or task message where live service map was updated.

## Pitfalls

- **Confusing git push with live deployment.** For static frontends, `origin/main` advancing does not prove the server is serving the new build. Always compare the live build sentinel (for example `curl $PUBLIC_URL/den-web-build.json`) against the expected commit before telling the user changes are live. If stale, deploy the static assets, restart/reload the service if it caches files in-process, then smoke the public URL.
- **Serving stale embedded assets after deployment.** A new static service can be correct while the old backend still serves an embedded UI on another route/port. Plan a follow-up retirement task and smoke both the public route and the old backend root.
- **Updating files without restarting a caching static service.** Some Node/static services load sentinel/config/static paths at startup or keep process-level caches; after replacing `wwwroot`, verify the live HTTP response, not just the remote filesystem. If filesystem and HTTP disagree, restart the service with the approved sudo/systemd path and re-check the sentinel.
- **Incorrect asset cache detection.** Vite asset hashes are not guaranteed lowercase hex; cache-header code should match mixed-case/base64url hash segments.
- **Dropping proxy query strings.** Smoke endpoints like `/api/channels?limit=1` can silently test the wrong request if the static proxy rebuilds paths without `search`.
- **Runtime config without leading slashes.** For frontend API bases, prefer `/api`/`/den-core-api` style absolute paths so nested routes do not resolve them relatively.
- **Route namespace collisions between backends.** A frontend proxy may already route broad prefixes like `/api/*` to one backend. Smoke the exact public path and identify the owning service before wiring a new feature. For Den Web, `/api/gateway/*` has been used by Den Channels Gateway APIs; a separate den-gateway service may need a distinct public prefix plus explicit rewrite.
- **Claiming deploy completion before live smoke.** Build/test success plus service restart is not enough; prove the public URL serves the expected build and can reach backend APIs through the configured proxy.
