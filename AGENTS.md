# GoblinBench Agent Guide

GoblinBench is Patch's Den/Hermes model and agent evaluation lab. This file is the fast-path briefing for agents working in this repo.

## Source of truth and current runner

- **Primary runner:** `python3 scripts/gb-run.py`
- **Canonical results DB:** `runs/goblinbench.sqlite`
- **Maintained store CLI:** `python3 scripts/gb-store.py`
- **Maintained report CLI:** `python3 scripts/gb-report.py`
- **Legacy query CLI:** `python3 scripts/gb-results.py` using `runs/goblinbench-results.sqlite`
- Python is the current in-repo runner path. Do **not** revive or depend on old .NET runner code.

The canonical DB is the durable record. On-disk `runs/run-*` directories are scratch/debug artifacts and are ring-buffered; older run dirs may disappear while DB history remains.

## How to run tests so results land in the DB

Use `gb-run.py`. It writes `runs/<run-id>/run.json`, runs scorers, then auto-ingests into `runs/goblinbench.sqlite`.

Examples:

```bash
# Deterministic smoke, no model calls
python3 scripts/gb-run.py --suite orchestrator --candidate scripted-deterministic

# One scenario/candidate
python3 scripts/gb-run.py \
  --scenario coding.maintainability-mini-service-python \
  --candidate pi-coding-glm52-den-router

# Suite/candidate matrix
python3 scripts/gb-run.py --suite coding --candidate pi-coding-glm52-den-router,pi-coding-gpt4o
```

If a benchmark matters beyond a one-off scratch experiment, make it a first-class GoblinBench scenario/candidate/scorer path rather than only writing ad-hoc JSON under `runs/`. Otherwise it will be invisible to `gb-store`, `gb-report`, and future agents.

For custom probes (local inference, prefill latency, service stress, etc.), prefer one of these before calling the work “stored”:

1. Add a suite/scenario JSON under `suites/<suite>/` and a runner/scorer that captures the measurement.
2. Or emit a compatible `runs/run-*/run.json` and run `python3 scripts/gb-store.py import`.
3. If it must stay experimental, write a durable doc under `docs/` and clearly state that the data is **not in the canonical DB**.

## Inspecting the canonical store

```bash
# DB size, row counts, latest run
python3 scripts/gb-store.py status

# Recent runs
python3 scripts/gb-store.py list --limit 20

# Filtered run lists
python3 scripts/gb-store.py list --suite coding --limit 20
python3 scripts/gb-store.py list --model glm52 --limit 20

# One run's cells and pass/fail summaries
python3 scripts/gb-store.py get <run-id>

# Label a run for future recall
python3 scripts/gb-store.py label <run-id> "short descriptive label"
```

Avoid raw `sqlite3` unless the CLIs cannot answer the question. The CLI encodes GoblinBench semantics and keeps large artifacts out of context.

## Report generation

Use reports for model/scenario comparisons instead of hand-crawling raw run dirs.

```bash
# Model × scenario grid
python3 scripts/gb-report.py --suite coding --view grid \
  --narrative "Comparing coding models on maintainability scenarios." \
  --out /tmp/goblinbench-coding-grid.html

# Failure triage
python3 scripts/gb-report.py --runs <run-id> --view failures --out /tmp/goblinbench-failures.html

# Single-cell deep dive
python3 scripts/gb-report.py --model glm52 \
  --scenario coding.maintainability-mini-service-rust \
  --view cell \
  --out /tmp/goblinbench-cell.html
```

`--narrative` is for the agent's short interpretation. The structured evidence comes from the DB.

## Legacy results CLI

`gb-results.py` still exists for ad-hoc aggregate queries over the old rebuildable index:

```bash
python3 scripts/gb-results.py import --reset
python3 scripts/gb-results.py runs --limit 20
python3 scripts/gb-results.py compare --suite coding --by model --format table
python3 scripts/gb-results.py failures --model minimax --limit 20
python3 scripts/gb-results.py cell <run-id> <scenario-id> <candidate-id> --format json
```

Prefer `gb-store.py` / `gb-report.py` for current work unless you specifically need the legacy aggregate commands.

## Store management and safety

```bash
# Import any existing run-*/run.json files into the canonical DB
python3 scripts/gb-store.py import

# Ring-buffer on-disk run dirs; DB untouched
python3 scripts/gb-store.py prune --keep 20

# Compact DB
python3 scripts/gb-store.py vacuum
```

Deletion is intentionally guarded:

```bash
# Single run delete, DB-only by default
python3 scripts/gb-store.py delete --run-id <run-id>

# Bulk delete needs a filter and --yes; use dry-run first
python3 scripts/gb-store.py delete --suite coding --dry-run
python3 scripts/gb-store.py delete --suite coding --yes
```

Do not delete or vacuum casually during benchmark work unless the user explicitly asks for curation/cleanup.

## Writing or modifying benchmark scenarios

A useful GoblinBench scenario should have:

- A stable `id` with suite prefix, e.g. `coding.maintainability-mini-service-rust`.
- A version.
- Candidate input/prompt/config that captures the behavior being tested.
- Deterministic or bounded scoring where possible.
- Scorer details that explain failures without requiring raw transcript archaeology.
- Representative artifacts/samples small enough to embed in the store when practical.

For coding scenarios:

- Put reusable source projects under `fixtures/`.
- Let the runner copy fixtures per run; do not mutate canonical fixtures during a candidate run.
- Use existing scorer plugins when possible:
  - `coding-tests`
  - `structure-metrics`
  - `maintainability-metrics`
- Prefer language-specific tests that are meaningful but bounded. Tiny tasks produce style-noise; huge tasks produce incomparable sprawl.

For local inference / latency / prefill tests:

- Capture at least: model, provider/backend, endpoint, quantization/format, context settings, concurrency, prompt-token count, output-token cap, warmup policy, cache-busting policy, command, environment, and artifact path.
- Separate model-quality failures from harness/provider/runtime failures.
- Record endpoint-reported `prompt_tokens` as the real x-axis; requested target sizes are approximate.
- If comparing vLLM and Lemonade, note model format differences explicitly (e.g. vLLM fp16 safetensors vs Lemonade GGUF/Q6). Do not overclaim backend superiority from non-equivalent formats.

## Verification expectations

Before reporting success:

1. Run the narrowest relevant command/test.
2. If changing runner/store/report code, run the relevant pytest(s), e.g.:

```bash
pytest tests/test_store_reporting.py -q
pytest tests/ -q
```

3. Check store ingestion when the task is about benchmark results:

```bash
python3 scripts/gb-store.py status
python3 scripts/gb-store.py list --limit 5
```

4. Report exactly what was run and where artifacts/DB rows landed.

Do not claim a result is in the DB unless `gb-run.py` auto-ingested it or `gb-store.py import/list/get` verifies it.

## Context hygiene

- Prefer DB/report pointers over dumping raw transcripts into chat.
- Keep large benchmark outputs in artifacts/docs and cite paths.
- Label important runs.
- If a result is only in side-channel artifacts (for example `runs/local-prefill-latency/...`), say so and either promote it into the canonical store or document why it remains experimental.
