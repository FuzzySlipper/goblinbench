---
name: den-web
description: "Implement, test, deploy, and live-verify Den Web frontend changes, especially UI/API contract fixes across Den Core, Channels, Gateway, and document workflows."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [den, den-web, frontend, vite, react, deployment]
    related_skills: [den-mcp, dogfood, requesting-code-review]
---

# Den Web

Use this skill when working on `/home/dev/den-web` or the mounted Den Web checkout: UI rendering bugs, API-client shape mismatches, document/task/channel screens, Vite/Vitest coverage, production static deployment, or live browser verification of Den Web.

## Default workflow

1. **Start from Den as source of truth.** Read the task, workflow summary, relevant documents/messages, and live API evidence before changing code. If the UI claims data is missing, independently verify the Core/Channels/Gateway endpoint payload.
2. **Use an isolated worktree for task changes.** Prefer a branch from `origin/main` under `/tmp/den-web-task-<id>` unless the task specifies a prepared branch. Avoid disturbing unrelated local repo state.
3. **Reproduce across layers.** Check browser/UI behavior, network/API response shape, client normalization, component filtering/rendering, and CSS visibility before deciding where the bug lives.
4. **Patch at the narrowest stable contract boundary.** If Core returns a valid but variable wire shape, normalize in the Den Web API client and make the component tolerant of both legacy and normalized shape when practical.
5. **Add regression coverage for the real wire shape.** Den Web has source/client-level Vitest patterns; prefer a focused test that would fail on the stale assumption rather than only snapshotting UI text.
6. **Validate before review.** Run the targeted test, broader Vitest suite when feasible, TypeScript build/check, and `npm run build` before requesting review.
7. **Review before promotion.** Record the Den review round, no unresolved blocking findings, branch/head/base, and test evidence before fast-forwarding `origin/main`.
8. **Deploy and live-smoke when the task affects production UX.** Follow the standalone deploy docs, preserve runtime config, write/update the build sentinel, restart the static service if required, run the smoke script, then verify the real UI in a browser.
9. **Post durable Den evidence.** Include root cause, files changed, tests, review verdict, deployment target, smoke result, and live browser acceptance evidence in the task thread.

## Common validation commands

From the Den Web worktree:

```bash
npm test -- --run src/features/documents/DocumentDiscussion.test.ts
npx vitest run --reporter=verbose
npx tsc -b --noEmit
npm run build
```

Adjust targeted test paths for the feature under work.

## API-shape pitfall: optional/null fields

Do not assume Den Core wire payloads include every nullable field. Some root-level records may omit nullable fields entirely (for example, document-discussion root comments can omit `parent_comment_id`). Component logic that filters strictly on `=== null` can drop valid records whose field is `undefined`, while counts based on raw arrays still show data exists. Prefer nullish checks (`== null` / `!= null`) where omitted and null are equivalent, and normalize missing nullable fields in the API client.

See `references/document-discussion-comment-shape.md` for a concrete document-discussion regression pattern.

## Regression pitfall: local fix vs promoted/deployed fix

A Den Web regression can reappear when the correct patch exists only as uncommitted changes or on a stale task branch/worktree. During root-cause investigation, compare all three states before assuming the code is already fixed: (1) live build sentinel and deployed asset, (2) `origin/main` at the deployed commit, and (3) local dirty branches/worktrees. If a previous fix is present only locally, re-create it as a reviewed task branch from `origin/main`, add regression coverage for the live wire shape, promote fast-forward to `main`, deploy, and browser-verify the production URL.

- **Worker Pool lobby shape:** Channels returns a raw lobby payload (`lobbyChannelId`, `totalMembers`, `byRole`, `members[].memberIdentity`, `status: "idle"`) that must be normalized in the API client before rendering. See `references/worker-pool-lobby-shape-regression.md`.

## Direct Channels and session-policy UI pitfalls

When Gateway-decommission or Channels/session work is in scope, do not use old Gateway channel/membership paths as the product model. Prefer direct Core/Channels/den-host ownership boundaries, linked-channel APIs for shared/system lanes, and active-work/session-owner projections for continuation UX. Den Web copy must distinguish source channel metadata from concrete agent-instance/session-owner truth, especially around `/new` and reset/continue controls. Direct-agent chat rendering should keep the human request body primary and delivery summaries secondary. If Den Web shows the direct-agent body correctly but the receiving Hermes agent says the message still comes through as generated/pending/claimed text, switch layers: inspect the Hermes `platforms/den_channels` adapter event-to-delivery mapping and verify the receiver's actual session DB/reply, not just Channels readback. Participant-list cleanup for departed agents needs Channels membership age/filter support (`updatedAt`/`leftAt` or `leftGraceMinutes`) before Den Web can apply a grace-period UI filter. See `references/direct-channels-and-session-policy-ui.md` for the API contracts, UI labels, regression-test scenarios, and deployment smoke caveats.

### Human channel messages may need a separate agent wake bridge

For channels with agent members, a successful Channels message write is not necessarily enough to wake Hermes agents if the agents poll a separate direct-agent-events API. When a task says agents poll direct wake events, add an explicit best-effort wake bridge from the Den Web human send path: after the channel message succeeds, filter active agent memberships and POST one wake event per agent. Keep slash commands from waking text agents unless required. If a Planner/user wake repeats a recently completed Den Web task, inspect `git log`, source, and tests before re-implementing; it may be an adapter replay or duplicate direct-agent wake rather than fresh work. See `references/channel-human-message-agent-wake.md` for the task #1930 contract, duplicate-request check, file touchpoints, and regression tests.

### `#den-system` is more than a singleton system-channel slug

When a task references showing `#den-system` in Den Web, verify the current Den task acceptance criteria before applying only a slug-list patch. The fuller linked-channel funnel model prefers `GET /api/projects/{projectId}/linked-channels` over old project-default lanes, shows linked-project attribution/filtering, and hides or de-emphasizes legacy `#project-den-*` channels while preserving non-Den fallback behavior.

## Deployment notes

- The production static root may be on `den-srv` under `/data/services/den-web/wwwroot`.
- Preserve runtime config such as `den-web-config.json` during `rsync --delete` deploys.
- The static service can cache config/sentinel at startup; restart the service after replacing `wwwroot` when the deployment docs require it.
- Use the Den Web smoke script with an expected build commit/sentinel when available, then browser-verify the user-visible acceptance criterion.

## Completion checklist

- [ ] Den task/message evidence read.
- [ ] UI/API/client/component layer inspected.
- [ ] Focused patch and regression coverage committed.
- [ ] Targeted tests, broader tests/typecheck/build run or blockers recorded.
- [ ] Review verdict recorded before promotion.
- [ ] Production deployment/smoke/browser verification completed when applicable.
- [ ] Den task updated with completion evidence and queue-drain behavior followed.
