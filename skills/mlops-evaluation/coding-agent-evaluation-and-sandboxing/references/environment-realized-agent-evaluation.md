# Environment-realized agent evaluation

## When to use this lane

Use this when selecting expensive models, profiles, or agent products for the environment in which they will actually run. Keep it separate from normalized direct-model tests: it measures **realized agent performance**, not raw model capability.

Examples of substrates:

- persistent coding-agent app servers using thread/turn protocols;
- worker/profile runtimes with task queues, context assembly, tool catalogs, and completion packets;
- CLI agents against a copied workspace.

## Two-lane reporting

| Lane | Question | Keep fixed |
|---|---|---|
| `model-core` | Can the model perform a narrowly defined behavior under a normalized protocol? | prompt, typed tools, fixture, scorer |
| `environment-realized` | Does the deployed agent/profile complete useful work in its real loop? | scenario/fixture/outcome oracle; record the environment rather than pretending it is neutral |

Never silently merge these into one model leaderboard. A model can be strong in either lane for different reasons.

## Adapter contract

Add a substrate-specific candidate runner before any generic `CodingAgent` runner. Normalize its output into standard GoblinBench artifacts:

```text
fixture workspace snapshot + diff
terminal status / timeout / retry state
requested and resolved model/provider/config
agent substrate and version
role/profile/prompt-assembly identity
active tool catalog hash
thread/turn/worker event trace
command and tool cycles
context compaction events when observable
token / usage data and cost basis
normal coding tests, state checks, and quality metrics
```

The runner must distinguish:

1. infrastructure/substrate failure;
2. agent completion with no workspace change;
3. agent completion with a failing patch;
4. successful task outcome.

## Workspace and service hygiene

- Copy fixtures per candidate/scenario.
- Use a fresh agent thread/session unless the scenario intentionally tests session memory.
- Pin and record model/config/profile/tool setup; do not infer it from a display name.
- Do not modify shared agent-service configuration as part of a benchmark run.
- Use supported service APIs/protocols, never internal databases.

## Cost and performance

Record `cost_basis` explicitly:

- `metered` — provider price/usage is available;
- `estimated` — snapshot pricing is used;
- `subscription_opaque` — token/use may be known but marginal price is not;
- `unavailable`.

Record requested and resolved model identities, since agent products may reroute or apply profile defaults. Capture elapsed time, attempts, model calls, command/test cycles, and token usage when the substrate exposes them.

## Rollout pattern

1. Add one thin vertical slice against one nontrivial existing coding fixture.
2. Add deterministic/mock protocol tests for lifecycle parsing and terminal failure.
3. Verify the real substrate once; preserve event/diff/test artifacts.
4. Add provenance/reporting before large matrices.
5. Only then run expensive model/profile comparisons and interpret task shape, cost, and reliability together.
