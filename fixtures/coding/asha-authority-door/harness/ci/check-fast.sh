#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
python3 harness/check_boundaries.py
python3 harness/check_guidance.py
cargo test -q -p rule-door -p sim-replay -p render-projection
cargo run -q -p protocol-codegen -- --check
if [[ ! -x node_modules/.bin/tsc ]]; then
  npm install --ignore-scripts --no-audit --no-fund
fi
npm test

