#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --no-fail-fast
cargo run -q -p protocol-codegen -- --check
python3 harness/check_boundaries.py
python3 harness/check_guidance.py
if [[ ! -x node_modules/.bin/tsc ]]; then
  npm install --ignore-scripts --no-audit --no-fund
fi
npm test

