# Architectural expectations

The incremental decoder owns byte buffering, framing limits, checksum validation,
payload decoding, and resynchronization. It must not mutate replica state. The replica
owns sequence/idempotency policy and transactional staging; transaction operations
must not leak into committed storage before commit.

A strong implementation separates frame extraction from operation application, uses
bounded allocation based on the configured maximum before trusting payload length,
and makes invalid transitions rollback-free by validating before mutation. Solutions
are penalized for merging decoder and replica responsibilities, duplicating binary
parsing, or building one oversized ingest/apply function.
