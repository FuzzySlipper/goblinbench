# Mini ASHA design

This repository models a deliberately small cross-language engine slice. Its
size is not permission to collapse ownership boundaries.

## Three planes

### Runtime authority

`core-state` owns the live `RuntimeSession` and its typed `DoorCapability` and
`EnergyCapability` tables. A capability is a typed authority facet attached to
an Entity. There is no generic component bag.

`rule-door` is the sole mutation owner for door transitions. It validates a
`DoorIntent`, produces an accepted `DoorDomainEvent`, and applies that event.
Rejected intents leave state completely unchanged.

Time enters authority as an explicit integer tick. Rules must not read wall
clock time or use timers.

### Expression

`@mini-asha/policy-door` receives a generated `DoorPolicyView` and may propose a
generated `DoorIntent`. It does not receive a `RuntimeSession`, mutable state,
or an authority service.

Policies may choose *what to request*. They do not reproduce Rust validation,
spend energy, open doors, or declare a request accepted.

### Projection

`render-projection` derives a generated `DoorProjection` from accepted Rust
state. `@mini-asha/renderer-door` converts that projection into display data.
The renderer does not import policy and does not determine whether a door is
open.

## Door transition contract

An Entity with a door and energy capability may request an open or close
transition.

- Opening a closed door costs the door's configured `open_energy_cost`.
- Closing costs no energy.
- A transition is rejected when the entity or required capability is missing,
  the expected revision is stale, the door is still cooling down, the desired
  state already matches, or available energy is insufficient.
- An accepted event records all values needed to replay the transition:
  entity id, previous and new state, energy spent, accepted tick, resulting
  cooldown deadline, and resulting revision.
- Applying an event verifies its previous state and next revision. It must fail
  without partial mutation when a replay record is corrupt or out of order.
- A successful transition changes state only through the event applier.

## Replay

`sim-replay` starts from an explicit initial session and applies recorded
events in order. Identical inputs must produce the same stable state hash.
Replay never invokes policy, reads the clock, or silently skips an invalid
event.

## Generated border

`protocol-door` is the Rust wire source of truth. `protocol-codegen` emits the
TypeScript declarations in the contracts package. Generated files are compared
byte-for-byte in CI.

The protocol uses plain stable wire values. Internal maps, references, errors,
and implementation-only state never cross the border.

