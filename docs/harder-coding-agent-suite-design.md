# Harder Coding-Agent Suite Design

Den task: GoblinBench #2019

## Summary

The current GoblinBench coding suite is a useful agent-lab baseline: eight C# maintenance tasks, visible/strict tests, scenario-scoped artifacts, and clean report ergonomics. It is not yet a strong discriminator for high-performing coding agents. The next suite should add `coding-hard` scenarios that are still small enough to run repeatedly, but require deeper reasoning than one localized fix.

## What “harder” should mean

Hardness should be explicit rather than vibes. Use these dimensions when designing new scenarios:

| Dimension | Easy baseline | Hard target |
|---|---|---|
| Edit scope | One function/file | 2-5 files with coherent API behavior |
| Reasoning | Direct bug from prompt | Infer invariant from tests/docs/callers |
| Visible/strict split | Visible tests reveal most behavior | Visible tests cover happy path; strict tests hit edge semantics |
| Failure mode | Obvious exception | Subtle stale state, ordering, precision, or compatibility bug |
| API design | Fill missing code | Preserve public contract while changing internal structure |
| Regression diagnosis | None | Existing implementation has plausible but wrong partial behavior |
| Ambiguity | Prompt says exactly what to do | Prompt includes constraints/tradeoffs; tests enforce safe interpretation |
| Overfit resistance | Markers only | Hidden-like strict tests and marker checks for hardcoded shortcuts |

## Proposed `coding-hard` scenario backlog

### 1. Event dedupe with replay window

- **Shape:** Multi-file C# service that deduplicates events by id and source within a sliding window.
- **Visible tests:** basic duplicate suppression.
- **Strict tests:** window expiry, source-specific identity, timestamp boundary, out-of-order events.
- **Failure trap:** starter dedupes only by id forever, causing false suppressions.

### 2. Config merge with precedence and redaction

- **Shape:** Merge default, environment, user, and secret config layers.
- **Visible tests:** simple override.
- **Strict tests:** null delete semantics, array replacement vs merge, secret redaction in diagnostics.
- **Failure trap:** shallow dictionary merge leaks secrets or mishandles null.

### 3. Async retry with cancellation and jitter policy

- **Shape:** Retry helper with cancellation token, retryable/nonretryable exception taxonomy, and deterministic jitter provider.
- **Visible tests:** retries transient failure.
- **Strict tests:** cancellation stops immediately, nonretryable not retried, max attempts exact, jitter bounded.
- **Failure trap:** sleeps after cancellation or retries fatal errors.

### 4. Incremental index update

- **Shape:** Maintain searchable index from add/update/delete document events.
- **Visible tests:** add/search.
- **Strict tests:** update replaces old terms, delete tombstones, idempotent duplicate events, case normalization.
- **Failure trap:** append-only implementation leaves stale terms.

### 5. Permission matrix with inherited denies

- **Shape:** Role/group/user permission resolver.
- **Visible tests:** direct allow.
- **Strict tests:** deny precedence, group inheritance, explicit user override, unknown permission default.
- **Failure trap:** allows by first match or treats missing as allow.

### 6. Streaming parser with partial frames

- **Shape:** Parse newline-delimited or length-prefixed messages across chunk boundaries.
- **Visible tests:** complete frames.
- **Strict tests:** split multibyte chars, back-to-back frames, incomplete tail buffering, invalid frame recovery.
- **Failure trap:** assumes each chunk is one message.

### 7. Cross-project task link normalization

- **Shape:** Small frontend-ish URL builder library fixture.
- **Visible tests:** same-project link.
- **Strict tests:** cross-project dependency, missing project id safe state, parent/subtask/review links.
- **Failure trap:** falls back to current project silently.

### 8. Report aggregation with failed-run partial scores

- **Shape:** Aggregate benchmark results distinguishing runner success from scorer success.
- **Visible tests:** all-pass rows.
- **Strict tests:** timed-out candidate with partial patch, missing scores, mixed pass/fail scorers.
- **Failure trap:** reports partial score as clean pass.

## Fixture rules

Each hard scenario should include:

- clear prompt/ticket text;
- starter code that is plausible and partially correct;
- visible tests that a shallow agent can pass;
- strict tests that enforce the actual invariant;
- marker scans for hardcoded constants or forbidden shortcuts;
- `correct_patch.json` for deterministic validation;
- metadata describing hardness dimensions and expected failure traps.

## Scoring

The existing `coding-tests` scorer is enough for the first hard scenarios, but reports should preserve:

- visible pass/total;
- strict pass/total;
- marker count;
- runner status separately from test status;
- patch size/file count for diagnostics, not as a pass criterion.

A future `coding-hard` report section can add a hardness-tag matrix so results show which dimensions a model handles.

## Implementation plan

1. Add suite directory `suites/coding-hard/` and fixture root `fixtures/coding-hard/`.
2. Implement 2 initial hard scenarios first, not all eight:
   - `coding-hard.config-merge-redaction`
   - `coding-hard.streaming-frame-parser`
3. For each scenario:
   - write starter fixture;
   - write visible tests;
   - write strict tests;
   - create `correct_patch.json`;
   - verify starter partial score;
   - verify `coding-scripted` pass.
4. Run one clean real candidate after deterministic validation.
5. Promote more scenarios from the backlog once the pattern is proven.

## Current task boundary

Task #2019 is the design slice. Actual fixture implementation should be a follow-up task so the suite can be built deliberately with TDD and measured against clean model runs.
