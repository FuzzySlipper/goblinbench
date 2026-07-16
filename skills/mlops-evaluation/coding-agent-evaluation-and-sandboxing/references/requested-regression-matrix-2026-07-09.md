# Requested tool/deceptive/hallucination/codebase regression matrix (2026-07-09)

## When this applies

Use this pattern when Patch asks to rerun broad GoblinBench regression categories such as tool calling, deceptive/adversarial tool use, hallucination/groundedness, and codebase analysis after discovering older pre-DB results are missing from the canonical store.

## First audit: what is actually in the store

Canonical current store:

```bash
python3 scripts/gb-store.py status
python3 scripts/gb-store.py list --limit 100
```

For suite coverage, query `runs/goblinbench.sqlite` directly:

```bash
python3 - <<'PY'
import sqlite3
con=sqlite3.connect('runs/goblinbench.sqlite')
con.row_factory=sqlite3.Row
for r in con.execute('''
  select suite, count(distinct run_id) runs, count(*) cells, sum(primary_passed=1) passed
  from candidate_results group by suite order by suite
'''):
    print(dict(r))
PY
```

Old one-off artifacts may exist outside the canonical DB, especially `runs/report.{md,json,html}` or skill/Den references. Treat those as useful summaries but not durable raw evidence unless their referenced `runs/run-*` directories still exist.

## Category → current suite mapping

For Patch's broad category names, the current practical mapping is:

| User category | Suites / runner path |
|---|---|
| tool calling | `tool-call-behavior`, `mcp-tools` with `mcp-openai-tool-use` candidates |
| deceptive / adversarial tool calling | `mcp-tools-hard`, `mcp-session`, `den-mcp-ambiguity`, `den-mcp-ambiguity-hinted` |
| hallucination / groundedness | `autonomy-calibration`, `evidence-grounding` with `fuzzy-openai` candidates |
| codebase analysis | standalone `scripts/codebase-analysis-runner.py all --fixture den-core-v1 ...` |

Do not run coding-agent workspace suites for this request unless Patch separately asks for coding implementation benchmarks. Codebase analysis Mode A is a standalone static-packet review benchmark, not the same as `suites/coding/*`.

## Candidate-file pattern for den-router model matrices

Create separate candidate files per runner family because the same model list needs different `cli_command` / `config.runner` values:

- `candidates.denrouter-requested-mcp.json` → `cli_command: "mcp-openai-tool-use"`, `config.runner: "mcp-openai-tool-use"`.
- `candidates.denrouter-requested-session.json` → `cli_command: "mcp-openai-session"`, `config.runner: "mcp-openai-session"`.
- `candidates.denrouter-requested-fuzzy.json` → `cli_command: "fuzzy-openai"`, `config.runner: "fuzzy-openai"`.

Observed requested model IDs for this campaign:

```text
qwen-max
deepseek-flash
deepseek-pro
glm-5.2
longcat-2.0
grok-4.5
kimi-code
gpt-5.5-test-only
stepfun
mimo-pro
```

Smoke `/v1/models` first:

```bash
python3 - <<'PY'
import json, urllib.request
data=json.loads(urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=10).read())
print('\n'.join(m['id'] for m in data.get('data', [])))
PY
```

Parameter gotchas from the July 2026 campaign:

- `kimi-code`: set `temperature: 1.0`.
- `glm-5.2`: for MCP tool-use candidate config, use `reasoning_effort: "low"` and omit temperature. If `glm-5.2` is flaky, Patch indicated `glm52` is the alternate backend.
- Tool/fuzzy smoke showed `gpt-5.5-test-only` works through OpenRouter/den-router chat completions and tool calls, so it can be included as a pace-setting model.
- `longcat-2.0` returned empty content on a tiny `response_format=json_object` smoke, but the real fuzzy runner may still produce parseable output; treat that as a smoke warning, not an automatic exclusion.

## Smoke before full run

Do three cheap probes before scheduling a full matrix:

1. plain chat: `Reply exactly READY.`
2. tool call: a tiny fake `ping` tool and check for `tool_calls`
3. JSON mode: `response_format: {"type":"json_object"}`

Then run one real GoblinBench scenario for each runner family:

```bash
python3 scripts/gb-run.py \
  --suite mcp-tools \
  --scenario mcp-tools.customer-case-summary \
  --candidates candidates.denrouter-requested-mcp.json

python3 scripts/gb-run.py \
  --suite autonomy-calibration \
  --scenario autonomy-calibration.clear-smoke-test-after-patch \
  --candidates candidates.denrouter-requested-fuzzy.json
```

The fuzzy smoke can fail the behavioral scorer for some models while still proving routing works. Interpret scorer failures separately from HTTP/runner failures.

## Full campaign driver shape

Run suite groups sequentially; these are slow and some models take tens of seconds per cell:

```bash
python3 scripts/gb-run.py --suite tool-call-behavior --candidates candidates.denrouter-requested-mcp.json
python3 scripts/gb-run.py --suite mcp-tools --candidates candidates.denrouter-requested-mcp.json
python3 scripts/gb-run.py --suite mcp-tools-hard --candidates candidates.denrouter-requested-mcp.json
python3 scripts/gb-run.py --suite mcp-session --candidates candidates.denrouter-requested-session.json
python3 scripts/gb-run.py --suite den-mcp-ambiguity --candidates candidates.denrouter-requested-mcp.json
python3 scripts/gb-run.py --suite den-mcp-ambiguity-hinted --candidates candidates.denrouter-requested-mcp.json
python3 scripts/gb-run.py --suite autonomy-calibration --candidates candidates.denrouter-requested-fuzzy.json
python3 scripts/gb-run.py --suite evidence-grounding --candidates candidates.denrouter-requested-fuzzy.json
```

For codebase analysis:

```bash
python3 scripts/codebase-analysis-runner.py all \
  --fixture den-core-v1 \
  --model qwen-max,deepseek-flash,deepseek-pro,glm-5.2,longcat-2.0,grok-4.5,kimi-code,gpt-5.5-test-only,stepfun,mimo-pro \
  --judge-model deepseek-pro \
  --output-dir runs/requested-regression-matrix-YYYYMMDD/codebase-analysis-den-core-v1
```

Patch `scripts/codebase-analysis-runner.py` `MODEL_EXTRAS` to include `glm-5.2: {"reasoning_effort":"low"}` if it only has `glm52`/`glm`.

## 2026-07-09 outcome notes

The first complete rerun used driver `scripts/run-requested-regression-matrices-20260709.sh` and published public artifacts at `https://fuzzyslipper.github.io/den-web/goblinbench-regression-matrix-2026-07-09/`.

Store-backed aggregate winners by broad pass rate were `glm-5.2` and `qwen-max` (26/34, 76.5%) across tool/deceptive/grounding suites. Category shape mattered more than the aggregate: `qwen-max`, `glm-5.2`, `deepseek-flash`, and `longcat-2.0` hit 12/12 on basic tool-calling; `kimi-code` led deceptive/adversarial tool-calling at 10/16; `mimo-pro` hit 6/6 on hallucination/grounding but was weak on deceptive tool use (5/16).

Codebase-analysis Mode A (`den-core-v1`, judge `deepseek-pro`) top recall tier was `deepseek-pro`, `kimi-code`, and `mimo-pro` at 10/12 (83%), but `mimo-pro` had much weaker evidence/severity calibration. `stepfun` emitted only a tiny non-parseable response (`findings_count=0`) and should be reported as a Mode-A output/harness failure, not a judged quality score. If `judge_candidate` returns findings-only fallback (observed for `gpt-5.5-test-only` and `mimo-pro`), the leaderboard can compute TP/recall from per-finding judge records but qualitative prose fields are absent.

Report-generation fixes made during this campaign: add `glm-5.2` to `MODEL_EXTRAS` with `reasoning_effort: low`; filter `None` judge results out of codebase coverage-matrix headers/rows; add mobile viewport + narrow-screen horizontal scrolling/swipe affordance to `scripts/gb/report/envelope.py`.

## GPT-5.6 reasoning-effort extension — 2026-07-09

Follow-up campaign script: `scripts/run-gpt56-reasoning-regression-matrices-20260709.sh`. Public report: `https://fuzzyslipper.github.io/den-web/goblinbench-gpt56-reasoning-2026-07-09/`.

For reasoning-effort A/B runs, candidate files used `reasoning_effort: medium` and `reasoning_effort: high` with no temperature, `max_tokens: 16384`, and separate rows suffixed `reasoning-medium` / `reasoning-high`. Additional runner support was added for `fuzzy-openai` and `mcp-openai-session`; `mcp-openai-tool-use` already supported reasoning effort. `codebase-analysis-runner.py` now supports model specs like `gpt-5.6-sol-test-only@high`, routing to API model `gpt-5.6-sol-test-only` while labeling/reporting the row as `...-reasoning-high`.

Outcome: medium/high tied on aggregate store-backed pass rate for GPT-5.6 rows (66/102 each, 64.7%), with high slightly slower. Best store-backed GPT-5.6 rows were `luna` medium, `terra` medium, and `terra` high at 23/34 (67.6%), matching old `gpt-5.5-test-only` but below `glm-5.2`/`qwen-max` (26/34). Codebase-analysis Mode A initially appeared to swing hard against high effort: `terra` medium and `sol` medium hit 67% recall, while `terra` high and `sol` high reported 0%; `luna` high reached 25% while `luna` medium hit 0%. Treat those 0% high-effort codebase rows as suspect until rejudged: `sol` high extracted 27 candidate findings, but the judge response truncated mid-JSON and the fallback parser kept only the first 5 complete judged findings, all bonus/no-match, even though the raw judge response had already started matching `worker-release-before-completion`. For codebase-analysis, add truncation detection, chunk/batch judge prompts, retry invalid JSON, and report “judge incomplete” instead of silently converting partial judge output to 0% recall. Do not assume high reasoning improves agentic/codebase-review benchmarks; keep effort variants separate and report latency, but also audit judge completeness before drawing strong conclusions.

## Reporting

After each GoblinBench run, label the run immediately:

```bash
python3 scripts/gb-store.py label <run-id> "requested <suite> 10-model matrix YYYY-MM-DD"
```

Generate summary reports from the canonical store:

```bash
python3 scripts/gb-report.py \
  --runs <comma-separated-run-ids> \
  --view grid \
  --embed output \
  --limit 500 \
  --title "Requested tool/deceptive/hallucination matrix — YYYY-MM-DD" \
  --out runs/requested-regression-matrix-YYYYMMDD/<group>-grid.html
```

For public sharing, publish the compact summary and selected HTML reports through the `den-web` shared-pages publisher rather than linking raw `runs/` paths.
