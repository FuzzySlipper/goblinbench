# React Blank/Background Screen with No Console Errors

## Diagnostic Pattern

**Symptom:** User navigates to a view or clicks a button → entire React app goes to blank/background-only screen. Browser devtools console shows no errors. Network tab shows API calls succeeding (200).

**Root Cause:** A render-time JavaScript error (TypeError, ReferenceError) throws during React's render phase. With no ErrorBoundary wrapping the app root, React 18+ unmounts the entire component tree to prevent rendering corrupted output. The error may not appear prominently in console in production/production-like builds.

## Common Trigger: API ↔ Type Mismatch

The most frequent cause in data-driven UIs is a mismatch between the actual API response shape and the frontend TypeScript types:

### Investigation Steps

1. **Capture the actual API response**
   ```bash
   curl -s <full-api-url> | python3 -m json.tool
   ```
   Compare field names and shapes against the frontend's TypeScript type definitions.

2. **Trace the render path that crashes**
   Look for these patterns in the component:
   - `useMemo(() => helper(presence.someField), [presence])` — if `someField` is `undefined`, the helper may throw
   - `Object.entries(someObj)` — throws if `someObj` is `undefined` or `null`
   - Array methods on potentially-undefined props (`members.filter(...)`, `members.map(...)`)
   - Destructuring or property access on `undefined`

3. **Check for ErrorBoundary**
   ```bash
   grep -r "ErrorBoundary" src/
   ```
   If the app has no ErrorBoundary, any unhandled render error nukes the entire tree.

### Fix Approaches

| Approach | When to Use |
|----------|-------------|
| **Response mapper** — fetch raw API shape, transform to expected frontend type | API is already deployed and cannot be changed; frontend types are rich and well-instrumented |
| **Defensive guards** — add optional chaining, nullish coalescing, and `?? []` defaults | Quick patch to prevent crash; buys time for proper fix |
| **ErrorBoundary** — wrap the view in a React error boundary | Prevents the whole app from going blank, even if this or other views crash |
| **Align API to types** — change the API response to match frontend expectations | Both are under your control and the frontend type represents the canonical contract |

### Debugging Checklist

- [ ] Hit the API endpoint directly (curl/browser) and compare response to TypeScript types
- [ ] Check every property access in the view's `useMemo`/`useEffect`/render body
- [ ] Look for `Object.entries()`, `Object.keys()`, array spread on potentially-undefined values
- [ ] Verify `satisfies never` exhaustiveness checks don't mask runtime values outside the union
- [ ] Check if the component mounts conditionally (if yes, the crash only happens on navigation to that sub-view, not on initial page load)

## Real-World Example: Worker Pool Lobby Crash

**Scenario:** Clicking "Worker Pool" in the Agents tab blanks the entire Den Web UI. API returns 200 with valid JSON. No errors in console.

**Actual API response (Channels):**
```json
{
  "lobbyChannelId": 604,
  "totalMembers": 4,
  "availableCount": 4,
  "byRole": [{"role": "drift_checker", "count": 1, "members": [...]}],
  "members": [{"memberIdentity": "spawned-drift-checker", "status": "idle", ...}]
}
```

**What frontend expected (WorkerPoolLobbyPresence type):**
```typescript
interface WorkerPoolLobbyPresence {
  channelId: number;          // API has: lobbyChannelId
  totalCandidateCount: number; // API has: totalMembers
  roleCounts: Record<string, number>; // API has: byRole (different structure)
  members: [{ identity: string, availabilityState: 'available'|'busy'|..., ... }]
  // API members have: memberIdentity, status: "idle"
}
```

**Crash path:**
1. `usePolling` fetches → `res.json()` succeeds → `presence` is set to the API response
2. `buildLobbySummary(presence)` runs in `useMemo` → calls `Object.entries(presence.roleCounts)`
3. `roleCounts` is `undefined` (not in API response) → `Object.entries(undefined)` throws `TypeError`
4. No ErrorBoundary → React 18 unmounts entire tree → blank screen

**Fix: Response mapper pattern:**
```typescript
export function getWorkerPoolLobbyPresence(): Promise<WorkerPoolLobbyPresence> {
  return getChannels<RawWorkerPoolLobbyResponse>('/worker-pool/lobby/presence').then(raw => {
    // Map raw API fields to expected frontend type
    const roleCounts: Record<string, number> = {};
    for (const group of raw.byRole ?? []) {
      roleCounts[group.role] = group.count;
    }
    const members = (raw.members ?? []).map(mapRawWorkerPoolMember);
    return {
      channelId: raw.lobbyChannelId,
      availableCount: raw.availableCount,
      totalCandidateCount: raw.totalMembers,
      roleCounts, members,
      observedAt: new Date().toISOString(),
    };
  });
}
```

### Key Lessons from This Case

1. **"No console errors" does not mean no error** — React 8.x production builds suppress render-phase error logging. The app just vanishes.
2. **API 200 + valid JSON ≠ correct shape** — `res.json()` succeeds but the object structure is wrong. Always curl the actual endpoint and compare field-by-field against the frontend types.
3. **TypeScript types are compile-time only** — a type like `members: WorkerPoolMemberPresence[]` won't catch the API returning a different field name like `memberIdentity` vs `identity`.
4. **Union exhaustiveness can mask runtime values** — `default: return state satisfies never` in a switch on a type union will pass TypeScript but produce wrong output at runtime for values like `"idle"` that aren't in the union.
5. **Response mapper in client layer** is the cleanest fix when API is already deployed: fetch the raw shape, transform to the typed shape, keep the component unchanged.
