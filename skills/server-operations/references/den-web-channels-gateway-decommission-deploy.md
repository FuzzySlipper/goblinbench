# Den Web / Channels live deploy and smoke notes

Use this reference when deploying Den Web or Den Channels during direct Core/Channels migration work.

## Den Web static deploy sentinel

Den Web's standalone static server can serve a stale `den-web-build.json` after rsyncing a new `wwwroot`, even when the file on disk has the new commit. If the live sentinel still reports the old commit after deploy:

1. Verify the file on den-srv directly:
   - `ssh den-srv 'cat /data/services/den-web/wwwroot/den-web-build.json'`
2. Restart the static service:
   - `ssh den-srv 'sudo systemctl restart den-web.service'`
3. Wait for port 18080 and re-check:
   - `curl -fsS http://192.168.1.10:18080/den-web-build.json`
4. Then run the live smoke with `EXPECTED_BUILD_COMMIT`.

Capture this as a cache/service-restart issue, not as a failed deploy, if disk state is already correct.

## Gateway-decommission smoke interpretation

While Gateway decommissioning is incomplete, Den Web generic smoke may still report `/den-gateway-api/fleet-ops` 502 failures. Do not let that mask direct-route regressions:

- Treat `/den-core-api/*`, `/api/*` Channels, static root, runtime config, build sentinel, and exact feature route smokes as the primary gate for direct Core/Channels migration tasks.
- Report `/den-gateway-api/fleet-ops` 502 separately as a known legacy caveat unless the task specifically owns Fleet Ops replacement.

## Den Channels dependency handoff

When a Den Web feature needs participant or membership freshness, implement the projection in Den Channels first rather than guessing in the frontend. Good backend shape:

- lifecycle fields (`createdAt`, `updatedAt`, `leftAt`);
- filtering query params (`includeLeft`, `leftGraceMinutes`);
- default compatibility when no new params are supplied;
- targeted contract tests for active/recent-left/stale-left behavior;
- live route smoke through both Den Channels and Den Web proxy if applicable.
