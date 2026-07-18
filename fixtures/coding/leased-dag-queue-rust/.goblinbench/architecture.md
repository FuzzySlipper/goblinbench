# Architectural expectations

There is no single required implementation. A strong solution keeps graph admission
validation separate from mutable queue transitions, applies a single atomic mutation
only after the complete batch is valid, and centralizes lease-token checks so stale
owners cannot accidentally take a different transition path. Retry calculation belongs
in policy code. Dependency propagation should be explicit and bounded rather than
hidden inside unrelated claim selection.

Quality scoring penalizes concentrating the implementation in `queue.rs`, oversized
transition functions, duplicated token/state checks, and dependency-direction leaks
from policy or graph modules back into the mutable queue.
