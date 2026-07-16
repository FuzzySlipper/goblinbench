# Direct Channels routing and agent-instance session-policy UI

Use this reference when Den Web work touches Channels, session/active-work UX, or Gateway-decommission fallout.

## Architecture boundary after Gateway decommission

Den Web should not rebuild user-facing channel/session features around `/den-gateway-api` compatibility paths. Prefer direct service ownership:

- Den Core: projects, tasks, worker/assignment truth, documents, review/workflow records.
- Den Channels: channels, linked channels, channel messages, channel activity/direct-agent events, active-work routing.
- den-host: machine-local/Hermes-runtime host capabilities.
- den-gateway: transitional routing/pass-through only; do not make it the source of truth for new UI behavior.

For project channels, prefer direct linked-channel APIs over project-local channel filtering when the UI must show shared/system lanes:

- `GET /api/projects/{projectId}/linked-channels`
- `GET /api/channels/{channelId}/linked-projects`

UI behavior that proved useful:

- Prefer linked `#den-system` / shared project lanes over legacy `#project-*` default lanes when links exist.
- Keep old project-default lanes visible only as legacy/ad-hoc context; label them as legacy rather than silently making them primary.
- Attribute messages in shared lanes by target/source project metadata (`targetProjectId`, `sourceProjectId`, link metadata) so a shared channel does not look like one undifferentiated transcript.

## Agent-instance session policy UI

The accepted policy is `_global/agent-session-boundary-policy`: source channels/lanes are metadata, not durable workflow session owners. Den Web copy and controls must not teach the old “every channel lane is a session” model.

When touching session/active-work screens, distinguish these fields explicitly:

- Source context: source channel/control room, source project, thread.
- Target work: target project, task, assignment, worker run.
- Concrete active owner: `sessionOwnerId`, `agentInstanceId`, `poolMemberId`.
- Profile identity: useful label, but not sufficient to identify a pooled worker session.
- Runtime session evidence: `sessionId`/Hermes key, model/profile/backend, status/tool events.
- Reset scope: `agent_instance_global`, `task_series`, `assignment_run`, or explicit `source_lane`.

Do not label arbitrary source channels as “the session” or imply `/new` always resets only the selected source lane. If `/new` or reset is exposed, show the intended reset scope and route target before sending.

## Active-work routing contract to consume

Den Channels task #1873 defined active-work continuation routing:

- `POST /api/active-work/resolve`
- `GET /api/active-work/routes`

Resolution should be by explicit target work fields, not by the selected channel:

- `targetProjectId`
- `targetTaskId`
- `assignmentId`
- `workerRunId`
- `profileIdentity`
- `sourceChannelId` / `sourceProjectId` only as metadata

The response can include:

- `routeStatus`: `routed`, `no_active_route`, or `stale`
- route identity: `targetProjectId`, `targetTaskId`, `assignmentId`, `workerRunId`, `workerRole`
- owner identity: `agentInstanceId`, `profileIdentity`, `poolMemberId`, `sessionOwnerId`, `sessionId`
- source metadata: `sourceChannelId`, `sourceControlProjectId`
- activity: `lastActivityAt`, `assignmentPhase`, `isStale`
- `allowedActions`: commonly `ask`, `continue`, `reset`, `view_transcript`
- `handles`: transcript/trace/delivery/agent-detail links
- evidence sources consulted

## Direct-agent message display

For direct-agent / wake-request messages, treat the human request body as the primary chat content. Gateway/Channels-generated delivery summaries are useful status/evidence, but they should render as secondary metadata rather than replacing or preceding the user’s actual request.

Good Den Web pattern:

- Add a render-model helper such as `channelMessagePrimaryBody(message)` / `directAgentMessageDisplay(message)` so the precedence is unit-tested outside the React component.
- Preserve assignment/checkpoint/delivery badges, but keep them visually separate from the message body.
- Add regression coverage where `message.body` contains the human request and `message.summary` contains generated delivery status; the body must appear first/primary.
- Browser-smoke against a real direct-agent message when possible, checking both the request body and secondary summary placement.

## Participant lists and departed memberships

Do not hide `membershipStatus === 'left'` blindly in Den Web when a grace period is required. A correct participant-list cleanup needs membership age from Den Channels: `updatedAt`/`leftAt`, or a server-side normal/grace-filtered projection such as `includeLeft=false` / `leftGraceMinutes=30`.

Pitfall: the Gateway compatibility membership DTO historically exposed status and wake-policy fields but not `updatedAt`/`leftAt`, while Den Channels stored `channel_memberships.updated_at`. In that state Den Web can tell that a participant left, but not whether it left 5 minutes or 5 days ago. Hiding all left members violates the grace-period requirement; keeping unknown-age left members fails to stop accumulation. Create/complete the Channels API task first, then consume it in Den Web.

Preferred backend contract for this class:

- Preserve historical membership rows/events for attribution/audit.
- Expose `createdAt`, `updatedAt`, `leftAt` (where `leftAt` can be `updatedAt` when `membershipStatus === 'left'`) and optionally `membershipPurpose` on the membership projection Den Web consumes.
- Support server-side filtering for normal participant lists: include non-left memberships, include recent-left memberships within the grace window, omit stale-left memberships.
- Keep default compatibility behavior conservative unless the caller opts into `leftGraceMinutes` or `includeLeft=false`.

## Regression tests to add for this class

Add Vitest or backend contract coverage for:

1. Same durable agent reached from two source channels groups to the same `sessionOwnerId` / active owner.
2. Two workers sharing one `profileIdentity` remain distinct when `agentInstanceId` or `poolMemberId` differs.
3. `/new` / reset controls show explicit scope before sending.
4. Target task/run continuation does not require the original source channel.
5. Shared/system lanes show project attribution and legacy project-default lanes are de-emphasized when linked channels exist.
6. Direct-agent wake/chat messages render the human request body as primary content and generated delivery summaries as secondary metadata.
7. Departed participants remain visible within the grace period but disappear from normal participant lists after the grace window, without deleting history.

## Deployment/smoke note

During the Gateway decommission transition, generic Den Web smoke can still show expected failures for old `/den-gateway-api/fleet-ops` endpoints while static/Core/Channels/document checks pass. Record that as an expected lingering Gateway-decommission failure only when direct Den Web acceptance and direct Core/Channels smokes pass; do not use it to skip browser verification of the changed UI.
