#!/usr/bin/env bash
set -u -o pipefail

ROOT=/home/dev/goblinbench
cd "$ROOT"

STAMP=20260709
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

# Tool-calling core.
run_gb_suite "tool-call-behavior" "candidates.denrouter-requested-mcp.json" "requested tool-call-behavior 10-model matrix ${STAMP}" "01-tool-call-behavior"
run_gb_suite "mcp-tools" "candidates.denrouter-requested-mcp.json" "requested mcp-tools 10-model matrix ${STAMP}" "02-mcp-tools"

# Deceptive / hard fake-MCP shapes.
run_gb_suite "mcp-tools-hard" "candidates.denrouter-requested-mcp.json" "requested deceptive mcp-tools-hard 10-model matrix ${STAMP}" "03-mcp-tools-hard"
run_gb_suite "mcp-session" "candidates.denrouter-requested-session.json" "requested deceptive mcp-session 10-model matrix ${STAMP}" "04-mcp-session"
run_gb_suite "den-mcp-ambiguity" "candidates.denrouter-requested-mcp.json" "requested den-mcp-ambiguity baseline 10-model matrix ${STAMP}" "05-den-mcp-ambiguity"
run_gb_suite "den-mcp-ambiguity-hinted" "candidates.denrouter-requested-mcp.json" "requested den-mcp-ambiguity hinted 10-model matrix ${STAMP}" "06-den-mcp-ambiguity-hinted"

# Hallucination / autonomy / groundedness.
run_gb_suite "autonomy-calibration" "candidates.denrouter-requested-fuzzy.json" "requested autonomy-calibration 10-model matrix ${STAMP}" "07-autonomy-calibration"
run_gb_suite "evidence-grounding" "candidates.denrouter-requested-fuzzy.json" "requested evidence-grounding 10-model matrix ${STAMP}" "08-evidence-grounding"

# Codebase analysis Mode A standalone path.
CODEBASE_MODELS="qwen-max,deepseek-flash,deepseek-pro,glm-5.2,longcat-2.0,grok-4.5,kimi-code,gpt-5.5-test-only,stepfun,mimo-pro"
CODEBASE_DIR="$CAMPAIGN_DIR/codebase-analysis-den-core-v1"
echo

echo "=== RUN codebase-analysis den-core-v1 :: $CODEBASE_MODELS ==="
python3 scripts/codebase-analysis-runner.py all \
  --fixture den-core-v1 \
  --model "$CODEBASE_MODELS" \
  --judge-model deepseek-pro \
  --output-dir "$CODEBASE_DIR" \
  2>&1 | tee "$CAMPAIGN_DIR/logs/09-codebase-analysis.log"
echo -e "codebase-analysis\t$CODEBASE_DIR\trequested codebase-analysis Mode A 10-model matrix ${STAMP}\t$CAMPAIGN_DIR/logs/09-codebase-analysis.log" >> "$RUN_IDS"

echo

echo "=== GENERATING STORE REPORTS ==="
python3 - <<'PY'
import subprocess, pathlib
campaign = pathlib.Path('runs/requested-regression-matrix-20260709')
rows=[]
for line in (campaign/'run-ids.tsv').read_text().splitlines():
    if not line.strip():
        continue
    suite, run_id, label, log = line.split('\t', 3)
    if run_id.startswith('run-'):
        rows.append((suite, run_id, label))

groups = {
    'tool-calling': ['tool-call-behavior', 'mcp-tools'],
    'deceptive-tool-calling': ['mcp-tools-hard', 'mcp-session', 'den-mcp-ambiguity', 'den-mcp-ambiguity-hinted'],
    'hallucination-grounding': ['autonomy-calibration', 'evidence-grounding'],
}
for name, suites in groups.items():
    run_ids = [r for s, r, _ in rows if s in suites]
    if not run_ids:
        continue
    out = campaign / f'{name}-grid.html'
    title = f'Requested {name} matrix — 2026-07-09'
    subprocess.run([
        'python3', 'scripts/gb-report.py',
        '--runs', ','.join(run_ids),
        '--view', 'grid',
        '--embed', 'output',
        '--limit', '500',
        '--title', title,
        '--out', str(out),
    ], check=False)
print('Report files:', sorted(str(p) for p in campaign.glob('*-grid.html')))
PY

echo "Completed: $(date -Is)"
echo "Run IDs: $RUN_IDS"
