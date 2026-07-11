# Tool-fixture contract audit (task #5628)

## Question

Can the fake-tool/MCP benchmarks reject an agent for a **valid but unexpected** approach, rather than for a true safety, protocol, or task-quality failure?

## Static audit — 2026-07-11

Reviewed the tool-backed suites exercised during #5543, plus the shared direct OpenAI and stdio/HTTP fake-MCP executors.

### Checks performed

| Check | Result |
|---|---|
| Scripted expected arguments absent from advertised `required` fields | None found |
| Hidden exact free-text requirements (`note`, `body`, `message`, etc.) | None found after the invoice draft-note repair |
| Expected-call scorer ordering | Order-independent; expected calls may occur in any order |
| Retry/recovery behavior | Extra retry attempts are retained and recovery is scored separately |
| Advertised tools without a scripted success path | Present by design as decoys/unavailable actions; fixed misleading success response |

### Broader-schema pass

A full scan found a second class of mismatch: **25** scripted arguments in legacy tool-backed suites were expected by fixture state but were not required by the advertised schema. They split into:

- **safe defaults / presentation knobs** (`labels: []`, `verbose`, `comment_kind`, document `tags`/`doc_type`, message metadata/intent): removed from canned expectations so omission and equivalent defaults remain valid;
- **identity or targeting values** (project/task IDs, document slug, alert/package identifiers, security version): retained as task-semantic constraints and slated to be explicit schema requirements where the scenario relies on them.

The Den-MCP ambiguity generator now emits the first class without optional defaults for both baseline and hinted variants; the error-recovery fixtures no longer require an empty `labels` array.

### Contract correction

Previously, an advertised tool with no canned behavior could return a synthetic successful response such as `{"ok": true, "note": "no canned result"}`. That conflated an intentionally unavailable decoy with a successful alternative path.

The direct OpenAI fake-tool runner and the stdio/HTTP fake-MCP server now share `execute_fake_tool` behavior:

1. validate the portable JSON-Schema subset before consuming fixture state;
2. preserve the scripted step after invalid calls, so recovery remains possible;
3. return a non-retryable structured **unavailable** response for an advertised-but-unscripted tool;
4. keep identity-bearing scripted arguments exact, but permit declared semantic matchers such as `$any_nonempty_string` for safe free text.

This makes a model's unsupported detour observable without falsely rewarding it, while still allowing it to recover through the intended safe path.

## Deliberate strictness that remains

The hard suites deliberately require exact IDs/operations when they represent the safety boundary: invoice/vendor IDs, production project IDs, service IDs, incident IDs, and destructive operation names. These are not prose preferences; accepting a nearby value would weaken grounding and safety measurement.

## Remaining intentional strictness

The remaining expected-but-optional fields are not prose defaults. They are task-grounding values: project/task scope in Den routing probes; customer status; alert/package identity; and the target project/reminder payload in safe-write probes. They remain scorer-visible because omitting them changes the requested target or broadens a query beyond the scenario's explicit context.

The API schemas keep Den `project_id` and `task_id` optional where the real MCP API allows broader queries. This avoids presenting a fake API contract just to force benchmark behavior. The runner records a recoverable validation failure if the canned target cannot be safely identified, and the scorer separately reports the argument mismatch. A future stateful fake Den service could model safe global-search alternatives directly.

## Follow-up candidates

- Add additional declared semantic matchers only where the task truly permits multiple values or free-form safe effects—not for identity-bearing actions.
- Consider richer final-state scoring for larger multi-step fake services, where multiple read-only investigation paths may be equally valid.
- Keep direct and network fake-tool contract tests paired whenever new schema keywords or matcher forms are introduced.
