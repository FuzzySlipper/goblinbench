#!/usr/bin/env bash
# Run den-mcp-ambiguity suite A/B matrix: baseline + hinted × 6 working den-router models
set -euo pipefail
cd /home/dev/goblinbench

CANDIDATES=(
  den-router-deepseek-flash-tool-behavior
  den-router-deepseek-pro-tool-behavior
  den-router-kimi-tool-behavior
  den-router-mimo-tool-behavior
  den-router-mimo-pro-tool-behavior
  den-router-minimax-tool-behavior
)

RUN_IDS=()
LOG="/tmp/goblinbench-ambiguity-matrix-$(date +%Y%m%d-%H%M%S).log"

echo "=== Den MCP Ambiguity A/B Matrix ===" | tee "$LOG"
echo "Candidates: ${CANDIDATES[*]}" | tee -a "$LOG"
echo "Start: $(date)" | tee -a "$LOG"

for variant in baseline hinted; do
  suite="den-mcp-ambiguity"
  if [ "$variant" = "hinted" ]; then
    suite="den-mcp-ambiguity-hinted"
  fi

  for cand in "${CANDIDATES[@]}"; do
    echo "" | tee -a "$LOG"
    echo "--- Running suite=$suite candidate=$cand ---" | tee -a "$LOG"
    start_time=$(date +%s)

    output=$(dotnet run --no-restore --project src/GoblinBench.Runner -- \
      --suite "$suite" \
      --candidate "$cand" 2>&1) || true

    run_id=$(echo "$output" | grep -oE 'run-[0-9]{8}-[0-9]{6}-[a-z0-9]+' | head -1) || true
    end_time=$(date +%s)
    elapsed=$((end_time - start_time))

    if [ -n "$run_id" ]; then
      echo "  => run_id=$run_id (${elapsed}s)" | tee -a "$LOG"
      RUN_IDS+=("$run_id")
    else
      echo "  => FAILED (no run_id, ${elapsed}s)" | tee -a "$LOG"
      echo "$output" | tail -20 | tee -a "$LOG"
    fi
  done
done

echo "" | tee -a "$LOG"
echo "=== All run IDs ===" | tee -a "$LOG"
for rid in "${RUN_IDS[@]}"; do
  echo "  $rid" | tee -a "$LOG"
done
echo "" | tee -a "$LOG"
echo "RUN_IDS=${RUN_IDS[*]}" | tee -a "$LOG"
echo "End: $(date)" | tee -a "$LOG"
