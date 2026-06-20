# GoblinBench Results CLI

`gb-results.py` is a lightweight, agent-friendly SQLite index over GoblinBench run artifacts.

Raw `runs/<run-id>/run.json` directories remain the evidence source. The SQLite database is a rebuildable query layer for fast comparisons, model lookups, failure summaries, and run-set/campaign views.

## Build / refresh the index

From the repo root:

```bash
scripts/gb-results.py import --reset
```

Default database:

```text
runs/goblinbench-results.sqlite
```

The importer currently indexes:

- `runs/run-*/run.json`
- candidate/scenario/score rows
- primary score/pass using the first non-`noop`, non-`latency` scorer with a pass value
- failure categories from scorer detail plus runner/HTTP/timeout categories
- artifact directories as repo-relative paths
- coherent run sets from `runs/<run-set>/run-ids.tsv` when present

The DB is disposable and can be rebuilt at any time.

## Common commands

List coherent run sets/campaigns:

```bash
scripts/gb-results.py run-sets
```

List recent runs:

```bash
scripts/gb-results.py runs --limit 20
```

Compare models on one suite:

```bash
scripts/gb-results.py compare --suite den-mcp-ambiguity --by model
```

Compare only a known run set:

```bash
scripts/gb-results.py compare \
  --run-set den-mcp-ambiguity-requested-20260612-054430 \
  --suite den-mcp-ambiguity-hinted \
  --by model
```

Show one model/candidate across all suites:

```bash
scripts/gb-results.py model glm
```

Show one model/candidate by scenario within a suite:

```bash
scripts/gb-results.py model glm --suite den-mcp-ambiguity-hinted --by scenario
```

Show expected suite coverage and skipped/missing scenarios for a model/candidate:

```bash
scripts/gb-results.py coverage --suite coding --model qwenmax
scripts/gb-results.py coverage --suite coding --model qwenmax --format tsv | awk -F'\t' '$3=="yes" {print $1}'
```

List failing cells with categories and artifact pointers:

```bash
scripts/gb-results.py failures --model minimax --limit 20
```

Drill into one cell, including scorer rows:

```bash
scripts/gb-results.py cell \
  run-20260612-055700-98421fa9 \
  den-mcp-ambiguity-hinted.den-mcp-doc-system-planner \
  den-router-minimax-tool-behavior \
  --format json
```

## Agent-friendly output modes

Every query command supports stable machine formats:

```bash
--format table   # default compact human table
--format json    # bounded JSON array
--format jsonl   # one object per row
--format tsv     # shell/sort/jq friendly
```

Examples:

```bash
scripts/gb-results.py compare --suite den-mcp-ambiguity --format json
scripts/gb-results.py failures --suite den-mcp-ambiguity --format tsv | sort -k9,9
```

Prefer the CLI over hand-crawling `runs/` in future agent sessions. It encodes the GoblinBench semantics for primary scorer selection, pass-rate aggregation, run-set membership, failure categories, and artifact pointers while keeping raw transcripts/traces out of context unless explicitly requested.

## Current limitations / next slices

- Run-set support is imported from existing `run-ids.tsv` files; the runner does not yet have a first-class `--run-set`/`--campaign` flag.
- The CLI is read/query oriented after import. It does not yet dual-write while a run executes.
- The DB stores artifact paths and score details, not full transcripts/traces. Use `cell` output to find artifact paths, then inspect the raw files only when needed.
- Aggregates are simple averages/pass counts. Repeated-run stability, flake detection, and regression comparison are natural next commands.
