# Gold architectural expectations

No one class layout is required. Appropriate solutions normally preserve these
ownership boundaries:

- definition validation owns graph/reference/cycle diagnostics and runs before writes;
- the repository owns shared mutable workflow state, creation ordering, and fencing
  token allocation so multiple engine instances cannot issue duplicate live claims;
- retry/readiness policy is domain logic, not event/persistence plumbing;
- the engine coordinates transitions while the outbox owns durable event sequencing;
- snapshots and events do not leak mutable repository references.

Behavior can pass with one giant `engine.ts`, but architecture scoring penalizes that
centralization, oversized transition functions, duplicated lease guards, and reverse
dependencies from validation/policy/storage into the coordinator. Small helpers are
welcome; speculative framework layers are not.
