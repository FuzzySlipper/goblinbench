# Rusty Crew external-agent runner

The `rusty-crew` runner is an environment-realized `CodingAgent` adapter. It
lets GoblinBench compare a Codex app-server turn driven directly with the same
model driven through Rusty Crew. Codex CLI support is not required for this
comparison.

GoblinBench owns this adapter. It uses Rusty Crew's supported HTTP API only; it
does not import Rusty Crew internals, inspect its database, or change Rusty Crew
production behavior.

## Debug-service safety boundary

Live benchmark runs default to and enforce:

- service unit: `rusty-crew-debug.service`;
- endpoint: `http://127.0.0.1:9348`.

Before creating a session the runner checks that exact user service is active.
It rejects another service-unit name or a non-loopback/non-9348 endpoint while
`require_debug_service` is true. The normal `rusty-crew.service` and its database
are therefore outside this benchmark path.

## Supported protocol surface

For each cell the adapter uses these public routes:

1. `GET /v1/external-runtimes` to require a ready runtime/controller.
2. `GET /v1/admin/profiles/registry` to require an active profile and capture
   tool identity.
3. `GET /v1/external-runtimes/{runtime_id}/events` to establish an event cursor.
4. `POST /v1/external-agent-sessions` with runtime, profile, copied-fixture CWD,
   label, and idempotency key.
5. `GET` and `POST /v1/external-bindings/{binding_id}/commands` to discover and
   apply supported `/model` and `/effort` settings.
6. `POST /v1/external-bindings/{binding_id}/messages` to request one durable
   external turn.
7. `GET /v1/external-turns/{request_id}` until a terminal phase.
8. The runtime events route again to retain the correlated durable event slice.

The runner copies the scenario fixture before session creation and passes only
that copy as the session CWD. It normalizes the result into the standard
`CandidateResult`, including the patch, changed files, exact requested/resolved
model settings, profile/runtime/session identifiers, terminal phase, usage, and
environment provenance.

The same execution-isolation prompt used by the direct app-server runner
requires a standalone `pwd` as the first command. GoblinBench validates its
literal output and the CWD on every durable command event; a missing, mismatched,
or outside-fixture observation fails the cell. The resolved `/effort` setting is
also checked against the requested value before message delivery.

Artifacts include:

- `rusty-crew-events.jsonl` (bounded to 2 MiB);
- `rusty-crew-response.txt` (bounded retained assistant text);
- `agent.patch`;
- the common `environment.json` envelope.

## Direct-versus-Crew comparison

The checked-in candidate matrix deliberately asks for the same Terra model and
reasoning effort on both paths:

```bash
python3 scripts/gb-run.py \
  --scenario e2e-pi-mock \
  --candidates candidates.codex-rusty-crew-comparison.json

# Repeat with the opposite execution order to expose warm-cache/order effects.
python3 scripts/gb-run.py \
  --scenario e2e-pi-mock \
  --candidates candidates.codex-rusty-crew-comparison.json \
  --candidate-order reverse

python3 scripts/gb-report.py --runs <run-id> --view environment \
  --out /tmp/codex-direct-vs-rusty-crew.html
```

Both cells are `environment-realized`: one names the direct app-server substrate
and the other names `rusty-crew-debug`. Reports keep them as distinct candidate
rows even when their resolved model is identical. `run.json.metadata` records
the selected order and the exact ordered candidate IDs.

## Current limits

- The adapter creates durable test sessions in the debug service and does not
  delete them; debug-store lifecycle remains Rusty Crew's responsibility.
- Cost is `opaque-subscription` because neither path exposes an attributable
  per-run subscription charge.
- Tool/command-cycle counts are populated only where the durable event schema
  exposes unambiguous events; unknown values remain unknown rather than zero.
