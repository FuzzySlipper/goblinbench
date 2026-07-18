# Contract change process

Rust protocol types are the only semantic source for the TypeScript border.

1. Change or confirm the wire shape in `crates/protocol-door`.
2. Update `crates/protocol-codegen` when the generator needs a new shape.
3. Run `cargo run -p protocol-codegen` from the repository root.
4. Run `cargo run -p protocol-codegen -- --check` to verify byte parity.
5. Compile and test TypeScript consumers through their root package exports.

Never repair contract drift by typing directly into a generated file. The
generator output is deterministic and checked byte-for-byte.

