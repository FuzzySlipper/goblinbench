# Replay and determinism

Replay is operational memory, not logging decoration.

- Every authoritative mutation is represented by an accepted DomainEvent.
- Events contain the accepted tick and resulting revision; replay does not
  consult current time.
- The applier checks the prior state and revision before mutating anything.
- Replay failures are explicit and leave the current replay state unchanged.
- Stable hashes serialize entities in numeric id order and use a specified
  byte-level hash. Do not depend on `HashMap` iteration or debug formatting.
- Policies and renderers are absent from replay.
- A rejected intent produces neither an event nor a state change.

