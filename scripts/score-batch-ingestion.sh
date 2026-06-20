#!/usr/bin/env bash
# Manual scoring runner for the batch-ingestion style probe.
# Run after the agent has completed the task.
# Usage: scripts/score-batch-ingestion.sh [--verbose]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURE_DIR="${SCRIPT_DIR}/../fixtures/coding/batch-ingestion"
RESULTS_DIR="${SCRIPT_DIR}/../runs/batch-ingestion-$(date +%Y%m%d-%H%M%S)"
VERBOSE=""

if [[ "${1:-}" == "--verbose" ]]; then
    VERBOSE="--verbose"
fi

mkdir -p "$RESULTS_DIR"

echo "=== Batch Ingestion Style Probe — Scoring ==="
echo "Fixture: $FIXTURE_DIR"
echo "Results: $RESULTS_DIR"
echo ""

# 1. Run the tests
echo "--- Running tests ---"
cd "$FIXTURE_DIR"

TEST_EXIT=0
python -m pytest tests/ -v --tb=short 2>&1 | tee "$RESULTS_DIR/test-output.txt" || TEST_EXIT=$?

if [ $TEST_EXIT -eq 0 ]; then
    echo ""
    echo "ALL TESTS PASSED"
    echo "{\"passed\": true, \"score\": 1.0}" > "$RESULTS_DIR/test-result.json"
else
    echo ""
    echo "SOME TESTS FAILED (exit code: $TEST_EXIT)"
    echo "{\"passed\": false, \"score\": 0.0}" > "$RESULTS_DIR/test-result.json"
fi

# 2. Run structure metrics
echo ""
echo "--- Structure Metrics ---"
python3 "${SCRIPT_DIR}/structure-metrics.py" "$FIXTURE_DIR" --output "$RESULTS_DIR/structure-metrics.json"
cat "$RESULTS_DIR/structure-metrics.json"

echo ""
echo "--- Done ---"
echo "Results saved to $RESULTS_DIR"
