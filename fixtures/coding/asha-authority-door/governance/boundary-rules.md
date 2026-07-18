# Boundary rules

1. TypeScript may never mutate authoritative state.
2. Policy receives a generated read-only view and returns a proposed intent.
3. Rust validates every intent and owns every accepted state transition.
4. Generated files under `ts/packages/contracts/src/generated/` are never
   hand-edited.
5. A lower Rust lane may not depend on a higher lane.
6. `core-state` may not depend on protocol, rules, replay, or projection.
7. `protocol-door` is a wire vocabulary crate and may not depend on state or
   rules.
8. `rule-door` may depend on state and protocol; it is the door mutation owner.
9. `sim-replay` may replay accepted events but may not invent or repair them.
10. `render-projection` derives display data and never mutates authority.
11. Policy may import only the root `@mini-asha/contracts` package.
12. Renderer may import only the root contracts package and may not import
    policy.
13. Sibling TypeScript packages are consumed through root barrels, never
    `/src`, `/dist`, or generated internal paths.
14. Deterministic authority uses explicit ticks and stable ordering, never wall
    clocks, randomness, or map iteration as wire order.
15. Rejected commands and invalid replay events leave authority unchanged.
16. Public vocabulary uses Entity, Capability, Rule, Policy, DomainEvent,
    RuntimeSession, PolicyView, and Projection rather than ECS or plugin terms.

