# GoblinBench SQLite Results CLI Pattern

Use the GoblinBench results CLI instead of hand-crawling `runs/` when answering cross-run/model/suite questions. It is designed to minimize agent token/tool cost by indexing run artifacts into SQLite and returning bounded table/json/jsonl/tsv results.

## Refresh the index

From `/home/dev/goblinbench`:

```bash
scripts/gb-results.py import --reset
```

Default DB:

```text
runs/goblinbench-results.sqlite
```

The DB is rebuildable. Raw `runs/<run-id>/run.json` and artifact directories remain the evidence source.

## Common agent queries

Compare models on a suite:

```bash
scripts/gb-results.py compare --suite den-mcp-ambiguity --by model
```

Restrict to a coherent run set/campaign imported from `runs/<run-set>/run-ids.tsv`:

```bash
scripts/gb-results.py compare \
  --run-set den-mcp-ambiguity-requested-20260612-054430 \
  --suite den-mcp-ambiguity-hinted \
  --by model
```

Show one model/candidate across all tests:

```bash
scripts/gb-results.py model glm
scripts/gb-results.py model glm --suite den-mcp-ambiguity-hinted --by scenario
```

Show expected suite coverage and skipped/missing scenarios for a model/candidate:

```bash
scripts/gb-results.py coverage --suite coding --model qwenmax
scripts/gb-results.py coverage --suite coding --model qwenmax --format tsv | awk -F'\t' '$3=="yes" {print $1}'
```

List failing cells with artifact pointers:

```bash
scripts/gb-results.py failures --model minimax --limit 20
```

Drill into one cell:

```bash
scripts/gb-results.py cell <run-id> <scenario-id> <candidate-id-or-model> --format json
```

## Output modes

Use stable machine formats for downstream agent processing:

```bash
--format table   # default human-readable
--format json    # bounded JSON array
--format jsonl   # one row per line
--format tsv     # shell/sort friendly
```

Prefer `--format json` or `--format tsv` when composing with `jq`, `sort`, or small scripts.

## Semantics encoded by the CLI

- Primary scorer = first non-`noop`, non-`latency` scorer with a `passed` value.
- Pass counts treat a missing primary pass as pass only when the runner succeeded.
- Failure categories are indexed from scorer detail plus runner errors/timeouts/HTTP-like failures.
- Artifact directories are returned as repo-relative pointers, not transcript dumps.
- Existing run sets are discovered from `runs/<run-set>/run-ids.tsv`.

## Pitfalls

- Refresh the index after new runs before answering historical/cross-run questions.
- Do not paste huge `run.json` or transcript files into context when a CLI aggregate or `cell` query is enough.
- The initial CLI is query/import only; runner dual-write and first-class `--run-set` creation are next slices, not current behavior.
