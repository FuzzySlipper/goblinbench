# Worker Pool lobby blank-screen regression

Concrete Den Web pattern from the Agents → WORKER POOL regression.

## Symptom

Clicking `Agents` → `WORKER POOL` causes the React app to collapse to the root/background until the page is reloaded. The API request succeeds with HTTP 200 and valid JSON, and the browser may only show a generic uncaught JS exception.

## Root cause pattern

The live Channels endpoint returns a raw worker-pool lobby shape:

```json
{
  "lobbyChannelId": 604,
  "totalMembers": 4,
  "availableCount": 4,
  "byRole": [{"role": "reviewer", "count": 1, "members": []}],
  "members": [{"memberIdentity": "spawned-reviewer", "role": "reviewer", "status": "idle"}]
}
```

The frontend render model expects normalized fields:

- `channelId`
- `totalCandidateCount`
- `roleCounts: Record<string, number>`
- `members[].identity`
- frontend `availabilityState` values, including live `idle`

If the API client returns the raw payload directly, render helpers such as `Object.entries(presence.roleCounts)` can throw during render and blank the app.

## Durable fix pattern

1. Normalize the raw Channels response in the API client before the component renders it.
2. Include live status values such as `idle` in `WorkerPoolAvailabilityState`, label helpers, and CSS-class helpers.
3. Add a defensive `presence.roleCounts ?? {}` guard in summary helpers where practical.
4. Add a Vitest regression using the actual raw wire shape (`lobbyChannelId`, `totalMembers`, `byRole`, `memberIdentity`, `status: "idle"`).
5. Verify the fix is in `origin/main` and the live build sentinel, not only in a dirty local worktree.
6. Browser-smoke the production URL after deploy: `Agents` → `WORKER POOL` should render role groups and worker rows with no JS errors.

## Verification checklist

- `npm test -- --run src/api/gateway/client.test.ts src/features/agents/workerPoolModel.test.ts`
- `npx tsc -b --noEmit`
- `npm run build`
- `npx vitest run --reporter=verbose`
- `EXPECTED_BUILD_COMMIT=<sha> DEN_WEB_URL=http://192.168.1.10:18080 npm run smoke:live`
- Browser console check after clicking `WORKER POOL`
