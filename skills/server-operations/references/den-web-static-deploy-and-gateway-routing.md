# Den Web static deploy and Gateway routing notes

Session source: Den Web Fleet Ops cockpit deployment work for task #1797.

## Durable lessons

- A successful `git push origin main` for `den-web` does **not** prove the live Den Web service is serving the new build. Always check the live build sentinel (`/den-web-build.json`) against the expected commit.
- The Den Web standalone static server reads runtime config and build sentinel at startup. After replacing `wwwroot`, restart `den-web.service` when live HTTP responses still show the old sentinel even though the filesystem has the new file.
- Preserve a timestamped backup of the previous static root before `rsync --delete` into `/data/services/den-web/wwwroot`.
- Run the repository smoke script against the public URL after deploy, with `EXPECTED_BUILD_COMMIT` set to the deployed commit.

## Route namespace pitfall

On the current Den Web static service, `/api/*` proxies to Den Channels. Therefore `/api/gateway/*` is already Den Channels Gateway traffic (memberships, channel gateway APIs), not necessarily the separate `den-gateway` service.

When adding a new backend service API for Den Web, do not assume `/api/gateway/...` is available just because the service is named `den-gateway`. Choose and document a non-conflicting runtime base such as `/den-gateway-api`, and have the static server explicitly rewrite that prefix to the backend's internal path (for example `/api/gateway`).

## Recommended deploy/smoke sequence

```bash
# In the reviewed den-web worktree
npm run build
commit=$(git rev-parse HEAD)
stage="/tmp/den-web-deploy-$commit"
rm -rf "$stage"
mkdir -p "$stage"
cp -a dist/. "$stage/"

# Write den-web-config.json and den-web-build.json into $stage.
# Include denGatewayApiBase explicitly, and avoid route collisions.

rsync -a --delete "$stage"/ den-srv:/tmp/den-web-stage/
ssh den-srv 'set -euo pipefail
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="/data/services/den-web/wwwroot.backup-${stamp}"
cp -a /data/services/den-web/wwwroot "$backup"
rsync -a --delete /tmp/den-web-stage/ /data/services/den-web/wwwroot/
sudo -n systemctl restart den-web.service
echo "backup:$backup"'

curl -fsS http://192.168.1.10:18080/den-web-build.json
EXPECTED_BUILD_COMMIT="$commit" DEN_WEB_URL=http://192.168.1.10:18080 npm run smoke:live
```

## Extra feature smoke

For features depending on a newly deployed backend route, add a feature-specific HTTP smoke after the generic static smoke. Example:

```bash
curl -fsS "$DEN_WEB_URL/$DEN_GATEWAY_BASE/fleet-ops" | jq 'keys'
```

If this returns `404` while the build sentinel and generic smoke pass, the problem is likely live service/routing deployment rather than the frontend build itself.

## den-gateway FleetOps live service notes

For the live Den Web FleetOps route from task #1810, `den-gateway.service` runs on `den-srv` as a system service and listens only on `127.0.0.1:5300`; Den Web rewrites `/den-gateway-api/*` to that service's internal `/api/gateway/*` routes.

Use `/data/services/den-gateway/{publish,data}` on `den-srv`, not `/home/dev/den-gateway` (absent on den-srv). Disable `DenGateway__DeliveryLoop__Enabled` for a FleetOps-only rollout unless the task explicitly intends to change live delivery-loop behavior.

Smoke both the route and the preserved Channels namespace:

```bash
curl -fsS http://192.168.1.10:18080/den-gateway-api/fleet-ops | jq '{service, actionCount: (.actions|length)}'
curl -fsS 'http://192.168.1.10:18080/api/gateway/memberships?projectId=den-web' | jq '{channelId, projectId, memberCount: (.members|length)}'
```

Known follow-up class: the API overview can work before action execution is fully wired. If `POST /den-gateway-api/fleet-ops/actions/.../runs` fails because `/home/agents/local/hermes-fleet/bin` is absent on `den-srv`, record it as a FleetOps action-script deployment/host-target follow-up rather than treating the route smoke as failed. Similarly, `systemctl --user` discovery from a system service may need explicit user-bus handling in a follow-up.
