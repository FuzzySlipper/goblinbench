# Rusty Crew runners

GoblinBench has two deliberately distinct Rusty Crew harness families:

- `rusty-crew` drives Crew's external Codex app-server runtime;
- `rusty-crew-native` drives Crew's Rust-owned `responses` or
  `chat_completions` brain selected by a model-provider alias.

Both are restricted to `rusty-crew-debug.service` by default. Results retain
the harness family and provider protocol; they must not be merged into one
unlabelled "Rusty Crew" lane.

## External Codex runner

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

## Native-brain runner

`rusty-crew-native` creates a disposable profile and then a distinct
benchmark-scoped session for every cell using
`POST /v1/admin/control/profiles` and `POST /v1/admin/control/sessions`. The
session sets `resourceLimits.workdir` to the copied fixture, bounds duration,
and disables delegation. The runner sends one message through the stable chat
API, replays durable events, captures bounded tool debug details while their
debug TTL is active, and hard-deletes the profile and its sessions in cleanup.
No Crew database or runtime config file is accessed directly.

The provider alias is authoritative. Its registered protocol selects Crew's
native brain, so the same runner supports both Responses-compatible and Chat
Completions-compatible providers:

```json
{
  "kind": "CodingAgent",
  "model": "deepseek-flash",
  "provider": "rusty-crew-native",
  "config": {
    "runner": "rusty-crew-native",
    "provider_alias": "deepseek-flash",
    "local_tool_profile_id": "full_agent"
  }
}
```

Run the checked-in isolated smoke with:

```bash
python3 scripts/gb-run.py \
  --scenario e2e-pi-mock \
  --candidates candidates.rusty-crew-native-smoke.json
```

The same native runner supports the text-only `autonomy-calibration` and
`evidence-grounding` suites. Those cells return the existing fuzzy decision
packet shape, but required actions are checked against observed Crew tool calls
instead of trusting `actions_taken`. When a tool produces evidence, required
evidence must be present in both the decision packet and the captured tool
result. Missing action boundaries, grounding, or required question details are
hard failures even when the weighted score equals the nominal threshold.

```bash
python3 scripts/gb-run.py --suite autonomy-calibration \
  --candidates candidates.rusty-crew-native-gpt56.json
python3 scripts/gb-run.py --suite evidence-grounding \
  --candidates candidates.rusty-crew-native-gpt56.json
```

It also supports the first-class `codebase-analysis.den-core-v1` scenario. The
candidate gets only the synthetic `repo-packet.md`; its gold ledger, decoys, and
deterministic scoring signals remain under the canonical fixture root and are
never copied into the session workdir. The runner requires observed read-tool
evidence, rejects mutations, parses the structured findings, and stores both
`analysis.md` and `findings.json` before the gold-ledger scorer runs.

Use the intentional-medium campaign wrapper for the current GPT-5.6 core
comparison. It selects all autonomy and grounding scenarios, the baseline
Go/TypeScript/Rust maintainability scenarios, and architecture analysis while
deliberately excluding fake-MCP suites:

```bash
python3 scripts/run-rusty-crew-gpt56-medium-core.py --dry-run
python3 scripts/run-rusty-crew-gpt56-medium-core.py
```

For the difficult native coding subset, use the dedicated campaign. It selects
only first-class copied fixtures and therefore keeps the same enforced workdir,
tool-locality evidence, debug-service restriction, teardown, scorer, and
canonical-store path as the core campaign:

```bash
# Two Rust systems scenarios + TypeScript baseline, Luna/Terra/Sol medium
python3 scripts/run-rusty-crew-gpt56-medium-hard.py --dry-run
python3 scripts/run-rusty-crew-gpt56-medium-hard.py

# Controlled TypeScript style prompt comparison on identical fixture/tests
python3 scripts/run-rusty-crew-gpt56-medium-hard.py \
  --language typescript --all-style-variants
```

The hard fixtures use a strict `coding-tests` behavior gate and an independent
`architecture-quality` score. The latter explains penalties for centralization,
seam loss, dependency-direction violations, large central functions, and
cross-file duplication without rewriting a behavioral failure as style feedback.

The wrapper invokes `gb-run.py` once, so all 30 cells share a run ID and are
auto-ingested into the canonical store. Pass `--candidate <id>` to certify one
model first.

The GPT-5.6 matrix expects active debug-service provider aliases
`gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol` using the native Responses
protocol. Crew's provider registration is the intended authority for
temperature, token limits, baseline reasoning effort, and other model-call
settings. The native runner selects the alias, validates its exact resolved
model and protocol, and records Crew's configured settings in provenance. It
does not create or modify provider registrations; the sole candidate-level
model-call exception is the session effort override described below.
GoblinBench never sends `max_tokens`, `maxTokens`, `max_output_tokens`, or
`maxOutputTokens` through this runner; those keys are rejected in candidate
configuration so a benchmark cannot accidentally reintroduce an output cap.

Native Crew sessions support an explicit session-scoped `reasoning_effort`
override. The runner applies it through
`POST /v1/admin/control/sessions/{session_id}/effort` after creating the isolated
benchmark session and before delivering the prompt. Use lowercase provider
tokens such as `low`, `medium`, or `high`; use `default` to explicitly clear the
session override and exercise the selected provider alias's baseline.

An explicit-effort cell must pass three checks: control-operation readback,
session-context resolution, and provider-request debug evidence. Responses runs
prefer the exact Rust-emitted `reasoning.effort` payload. On long multi-tool
turns where that retained debug object is truncated, they verify the complete
`ts_to_native_openai_responses` handoff's resolved `reasoningEffort` instead.
The runner stores this evidence in
`rusty-crew-native-provider-requests.jsonl` and fails the cell if an explicit
setting cannot be proven. Other model-call overrides such as
`temperature`, `top_p`, or token limits remain provider-owned and are rejected
in candidate config; `expected_reasoning_effort` is also rejected to avoid
confusing provider registry readback with a session override.

```json
{
  "runner": "rusty-crew-native",
  "provider_alias": "gpt-5.6-luna",
  "provider_protocol": "responses",
  "reasoning_effort": "high"
}
```

Artifacts include `rusty-crew-native-events.jsonl`,
`rusty-crew-native-tool-details.jsonl`, `rusty-crew-native-response.txt`, and
`rusty-crew-native-provider-requests.jsonl`, plus `agent.patch`. Environment
provenance records the provider alias/revision, protocol, brain
module/strategy/backend, profile/tool identity, session and wake IDs, cleanup
status, and the explicit harness family.

Crew task `#5846` supplied creation-time `resourceLimits.workdir` support. The
runner now fails before message delivery if the session readback does not match
the copied fixture and retains captured path/tool locality evidence in the cell.
Exact token usage and attributable cost remain unknown because the native chat
event contract does not currently expose them.

## Late provider failures and retained scoring

A native Responses wake can fail on a later replay request after earlier local
tools already produced a useful patch. GoblinBench treats this as two separate
facts: the runner remains failed with its typed timeout/provider error, while
the copied fixture, event evidence, partial response, and `agent.patch` remain
available to deterministic scorers. A recovered passing test score does not
erase `runner_error` or `timeout` from canonical provenance.

For runs created before that retention path was added, `gb-score.py` can infer
the fixture only from the candidate artifact sibling, provided it remains
inside the selected run directory:

```bash
python3 scripts/gb-score.py runs/<run-id> \
  --retry-failed --refresh-in-process
python3 scripts/gb-store.py import --run-json runs/<run-id>/run.json
```

The scorer writes a `post_score_events` receipt into run metadata and marks
scores produced from a recovered fixture. The maintained store import is
idempotent for a run ID.
