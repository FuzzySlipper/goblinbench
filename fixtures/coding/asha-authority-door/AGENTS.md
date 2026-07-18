# Mini ASHA Agent Guide

This fixture is a self-contained, synthetic architecture exercise inspired by
ASHA Engine. It is not an ASHA checkout and does not consume ASHA source code.

Read this file and the referenced governance documents before editing code.
The task is successful only when the feature works *and* remains in the
correct ownership lanes.

## Architecture soul

> Rust owns authority. TypeScript owns expression and projection. Generated
> contracts define the border.

- Rust owns canonical session state, validation, accepted events, application,
  replay, deterministic time, and projection generation.
- TypeScript policy reads generated immutable views and proposes intents. It
  never mutates authoritative state or decides whether a proposal is accepted.
- TypeScript rendering displays generated projections. It never infers or
  validates authority.
- Cross-language types originate in the Rust protocol crate and are generated
  into `ts/packages/contracts/src/generated/`. Never hand-edit generated files.
- Every crate and package is an assignment cell. Dependencies must agree with
  `governance/ownership.toml`.

## Required reading

- `docs/design.md` describes the stored/runtime/projection planes and the door
  transition lifecycle.
- `governance/boundary-rules.md` contains the enforceable dependency and
  authority rules.
- `governance/ownership.toml` declares the allowed crate/package edges.
- `docs/contract-change-process.md` explains generated contract updates.
- `docs/replay-and-determinism.md` defines replay and time requirements.

## Desired implementation style

Rust authority code should be boring: explicit state, explicit errors, explicit
events, narrow APIs, and deterministic inputs. Avoid clever abstractions,
ambient registries, callbacks, plugins, and generic component bags.

TypeScript should use named values and small functions with explicit verbs.
Avoid manager classes, hidden mutable state, deep imports, `any`, browser
globals in policy, and duplicated validation logic.

Use ASHA vocabulary:

- Entity, Capability, Rule, Policy, DomainEvent, RuntimeSession, PolicyView,
  Projection.
- Do not introduce public `Component`, `Archetype`, `WorldState`, `System`, or
  plugin terminology.

## Commands

Run the ordinary affected-surface gate while iterating:

```bash
./harness/ci/check-fast.sh
```

Run the complete visible gate before finishing:

```bash
./harness/ci/check-all.sh
```

Do not weaken tests, governance files, CI scripts, or guidance. Hidden scoring
adds further authority, replay, contract, and boundary checks.

