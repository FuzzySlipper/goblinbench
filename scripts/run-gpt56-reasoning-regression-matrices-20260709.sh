#!/usr/bin/env bash
set -u -o pipefail
ROOT=/home/dev/goblinbench
cd "$ROOT"
STAMP=20260709-gpt56-reasoning
CAMPAIGN_DIR="runs/requested-regression-matrix-${STAMP}"
mkdir -p "$CAMPAIGN_DIR/logs"
RUN_IDS="$CAMPAIGN_DIR/run-ids.tsv"
: > "$RUN_IDS"

echo "Campaign dir: $CAMPAIGN_DIR"
echo "Started: $(date -Is)"

run_gb_suite() {
  local suite="$1"
  local candidates="$2"
  local label="$3"
  local log_slug="$4"
  local log_path="$CAMPAIGN_DIR/logs/${log_slug}.log"
  echo
  echo "=== RUN $suite :: $label ==="
  echo "Log: $log_path"
  python3 scripts/gb-run.py --suite "$suite" --candidates "$candidates" 2>&1 | tee "$log_path"
  local status=${PIPESTATUS[0]}
  local run_id
  run_id=$(grep -m1 '^Run ID:' "$log_path" | awk '{print $3}')
  if [[ -n "${run_id:-}" ]]; then
    python3 scripts/gb-store.py label "$run_id" "$label" || true
    printf "%s\t%s\t%s\t%s\n" "$suite" "$run_id" "$label" "$log_path" >> "$RUN_IDS"
  else
    printf "%s\t%s\t%s\t%s\n" "$suite" "NO_RUN_ID_STATUS_${status}" "$label" "$log_path" >> "$RUN_IDS"
  fi
  echo "=== DONE $suite status=$status run_id=${run_id:-none} ==="
  return 0
}

# New GPT-5.6 family, reasoning_effort medium+high variants only.
run_gb_suite "tool-call-behavior" "candidates.gpt56-reasoning-mcp.json" "gpt-5.6 reasoning medium/high tool-call-behavior matrix 2026-07-09" "01-tool-call-behavior"
run_gb_suite "mcp-tools" "candidates.gpt56-reasoning-mcp.json" "gpt-5.6 reasoning medium/high mcp-tools matrix 2026-07-09" "02-mcp-tools"
run_gb_suite "mcp-tools-hard" "candidates.gpt56-reasoning-mcp.json" "gpt-5.6 reasoning medium/high deceptive mcp-tools-hard matrix 2026-07-09" "03-mcp-tools-hard"
run_gb_suite "mcp-session" "candidates.gpt56-reasoning-session.json" "gpt-5.6 reasoning medium/high deceptive mcp-session matrix 2026-07-09" "04-mcp-session"
run_gb_suite "den-mcp-ambiguity" "candidates.gpt56-reasoning-mcp.json" "gpt-5.6 reasoning medium/high den-mcp-ambiguity baseline matrix 2026-07-09" "05-den-mcp-ambiguity"
run_gb_suite "den-mcp-ambiguity-hinted" "candidates.gpt56-reasoning-mcp.json" "gpt-5.6 reasoning medium/high den-mcp-ambiguity hinted matrix 2026-07-09" "06-den-mcp-ambiguity-hinted"
run_gb_suite "autonomy-calibration" "candidates.gpt56-reasoning-fuzzy.json" "gpt-5.6 reasoning medium/high autonomy-calibration matrix 2026-07-09" "07-autonomy-calibration"
run_gb_suite "evidence-grounding" "candidates.gpt56-reasoning-fuzzy.json" "gpt-5.6 reasoning medium/high evidence-grounding matrix 2026-07-09" "08-evidence-grounding"

CODEBASE_MODELS="gpt-5.6-terra-test-only@medium,gpt-5.6-terra-test-only@high,gpt-5.6-luna-test-only@medium,gpt-5.6-luna-test-only@high,gpt-5.6-sol-test-only@medium,gpt-5.6-sol-test-only@high"
CODEBASE_DIR="$CAMPAIGN_DIR/codebase-analysis-den-core-v1"
echo

echo "=== RUN codebase-analysis den-core-v1 :: $CODEBASE_MODELS ==="
python3 scripts/codebase-analysis-runner.py all \
  --fixture den-core-v1 \
  --model "$CODEBASE_MODELS" \
  --judge-model deepseek-pro \
  --output-dir "$CODEBASE_DIR" \
  2>&1 | tee "$CAMPAIGN_DIR/logs/09-codebase-analysis.log"
echo -e "codebase-analysis\t$CODEBASE_DIR\tgpt-5.6 reasoning medium/high codebase-analysis Mode A matrix 2026-07-09\t$CAMPAIGN_DIR/logs/09-codebase-analysis.log" >> "$RUN_IDS"

echo

echo "=== GENERATING STORE REPORTS ==="
python3 - <<'PY'
import subprocess, pathlib
campaign = pathlib.Path('runs/requested-regression-matrix-20260709-gpt56-reasoning')
old_campaign = pathlib.Path('runs/requested-regression-matrix-20260709')
rows=[]
for path in (old_campaign/'run-ids.tsv', campaign/'run-ids.tsv'):
    if not path.exists():
        continue
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        suite, run_id, label, log = line.split('\t', 3)
        if run_id.startswith('run-'):
            rows.append((suite, run_id, label))

groups = {
    'tool-calling-combined': ['tool-call-behavior', 'mcp-tools'],
    'deceptive-tool-calling-combined': ['mcp-tools-hard', 'mcp-session', 'den-mcp-ambiguity', 'den-mcp-ambiguity-hinted'],
    'hallucination-grounding-combined': ['autonomy-calibration', 'evidence-grounding'],
}
for name, suites in groups.items():
    run_ids = [r for s, r, _ in rows if s in suites]
    if not run_ids:
        continue
    out = campaign / f'{name}-grid.html'
    title = f'GoblinBench {name.replace("-combined", "")} — old matrix + GPT-5.6 medium/high — 2026-07-09'
    subprocess.run([
        'python3', 'scripts/gb-report.py',
        '--runs', ','.join(run_ids),
        '--view', 'grid',
        '--embed', 'output',
        '--limit', '800',
        '--title', title,
        '--out', str(out),
    ], check=False)
print('Report files:', sorted(str(p) for p in campaign.glob('*-grid.html')))
PY

echo "Completed: $(date -Is)"
echo "Run IDs: $RUN_IDS"
