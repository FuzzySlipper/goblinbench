# Channel human-message agent wake bridge

## When this applies

Use this pattern when Den Web sends human-authored channel messages and agents poll a direct-agent-events API for wake messages. Posting to Channels alone may persist the channel message but not create the wake event an idle/polling Hermes agent consumes.

## Contract observed in task #1930

Den Web needed to call the direct-agent-events service after a human sends a channel message in a channel that has active agent members:

```http
POST http://192.168.1.10:18081/api/direct-agent-events
Content-Type: application/json
```

Payload shape:

```json
{
  "channelId": 123,
  "memberIdentity": "agent-identity",
  "body": "human message text",
  "senderIdentity": "human-identity",
  "sourceKind": "wake_event",
  "messageKind": "direct_agent_wake"
}
```

## Implementation shape

1. Keep the normal `postChannelMessage` flow as the durable channel write.
2. After a successful human-authored channel send, inspect channel memberships.
3. Filter to active agent members only; exclude the sender and inactive/left members when the membership model exposes status.
4. Emit one direct-agent wake event per target agent member.
5. Do not block the human message UX on wake failures unless the task explicitly requires fail-closed behavior; log/report enough evidence for debugging.
6. Keep slash-command or UI-command sends from waking text agents unless the command semantics explicitly require an agent response.

## Den Web files that were useful

- `src/api/channels/client.ts` — add/centralize the direct-agent-events POST helper.
- `src/api/channels/types.ts` — direct wake DTO shape.
- `src/features/channels/directAgentWake.ts` — small helper to filter members and build wake requests.
- `src/features/channels/ChannelChatPanel.tsx` — ordinary channel-message send path.
- `src/features/sessions/FocusedSessionView.tsx` — focused/session human-message path.

## Regression coverage

Add focused tests for:

- Emits wake events for active agent channel members.
- Does not emit for purely human channels.
- Does not emit to inactive/left members or the human sender.
- Continues the message send path if a wake POST fails, when best-effort wake is the intended behavior.
- Skips slash-command messages where relevant.

Run targeted Vitest first, then `npx tsc -b --noEmit`, broader `npm test -- --run`, and `npm run build` when feasible.

## Duplicate-request / adapter-replay check

Direct-agent wake work is easy to replay because the same Planner message may arrive again while validating the adapter. Before re-implementing, check `git status`, `git log -5`, and source for the wake helper/POST URL. If the relevant commits are already at `HEAD`, rerun the validation commands and report the existing commits rather than creating duplicate or empty changes. Keep unrelated dirty files untouched.

## Related system-channel UI lesson

For global/system channels, do not hardcode a singleton like `agent-commons` unless the product really has only one system lane. Keep global system channel slug lists extensible; task #1934 required including both `agent-commons` and `den-system` so `#den-system` appeared in Den Web.

Do not treat slug inclusion as the whole #1934 story unless the task says the simple fix is enough. The fuller `#den-system` funnel requires project-linked channel routing (`GET /api/projects/{projectId}/linked-channels`), linked-project attribution/filtering, and hiding/de-emphasizing old `#project-den-*` channels while preserving default-channel fallback for non-Den projects.
