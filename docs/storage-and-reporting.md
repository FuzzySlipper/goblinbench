# GoblinBench storage & reporting

Two layers, post-port:

1. **Canonical SQLite store** (`runs/goblinbench.sqlite`) — the durable record.
   Run metadata, scores, scorer detail, inline artifacts (patches, code samples,
   score breakdowns), and representative samples. Backup is `cp` of one file.
2. **On-disk run files** (`runs/<run-id>/`) — scratch space for *this run's*
   debugging. Written as before (so `grep`/edit work), but bounded by a **ring
   buffer**: the N most recent runs are kept, older ones auto-pruned. DB history
   is unaffected by pruning; re-run a scenario anytime to regenerate files.

This inverts the previous design (files canonical, DB a derived index). Losing
the files is no longer catastrophic — the DB holds the judgement and the code
samples; raw files are regenerable.

## The store (`scripts/gb/store.py`, CLI: `scripts/gb-store.py`)

Auto-ingested at the end of every `gb-run.py` invocation. Manual control spans
both query and management:

```bash
# inspection
gb-store status                      # row counts + on-disk run count + DB size
gb-store list [--suite X | --model Y | --older-than 30d]   # list runs with filters
gb-store get <run-id>                # one run's cells + per-cell pass/fail

# management
gb-store import [--reset]            # pull run-*/run.json into the DB
gb-store prune --keep 20             # ring-buffer the on-disk run files (DB untouched)
gb-store delete --run-id <id>        # delete one run from the DB (explicit → direct)
gb-store delete --suite X --yes      # bulk delete (needs a filter + --yes; --dry-run previews)
gb-store delete --keep-recent 50 --yes   # DB-side prune complement (keep N newest)
gb-store delete --older-than 90d --yes --files   # age-based, also remove on-disk dirs
gb-store label <run-id> ["text"]    # get/set a run's label (tag/note it)
gb-store vacuum                      # compact the DB (VACUUM)
gb-store artifact <cr_id> <name>     # dump one inline artifact to stdout (debug)
```

### Delete safety

Given how easy it is to lose data by accident, the delete commands are
opinionated about safety:

- **Single-run delete** (`delete --run-id X`) executes directly — you named
  the thing.
- **Bulk deletes** (any filter that matches >1 run) **require `--yes`** to
  proceed; without it they print what *would* be deleted and exit. `--dry-run`
  is always available to preview.
- **No filter at all is refused** — `gb-store delete --yes` with no selector
  does nothing rather than nuke the corpus. Use `delete --keep-recent 0 --yes`
  explicitly if you genuinely want to clear everything.
- `--files` also removes the on-disk run dir(s); default is DB-only.

This is the green path for agents managing the store — they never need to run
raw SQL or `sqlite3` against the DB.

Schema (extends the original gb-results schema with two tables):

- `artifacts(candidate_result_id, name, mime, size_bytes, content_bytes BLOB, external_path)`
  — inline content for artifacts under 256 KB (patches, scores, code, traces);
  larger artifacts (e.g. a 200 MB reasoning-model stdout) are referenced by path
  into the ring-buffered file tree.
- `representative_samples(candidate_result_id, kind, label, language, content, source_path)`
  — curated excerpts that summarize a cell's behavior (changed-file list +
  LOC deltas from maintainability-metrics, aggregate metrics from
  structure-metrics). The report tool reads these instead of re-walking raw
  files.

Ring buffer retention defaults to 20 run dirs; override via the
`GOBLINBENCH_RUN_FILE_RETENTION` env var.

## Git tracking

The canonical store (`runs/goblinbench.sqlite`) and on-disk run trees are
**committed to git** — git is the backup. The genuinely-regenerable heavy stuff
is gitignored so history doesn't balloon:

- **Tracked**: `goblinbench.sqlite`, run manifests (`run.json`), scores,
  traces, logs, patches, the surviving named campaign dirs.
- **Ignored**: copied `fixture/` trees, `bin/`/`obj/` build artifacts, agent
  scratch (`.tmp/`, `__pycache__/`, `node_modules/`, `target/`, …), the WAL/shm
  runtime files, and the legacy `goblinbench-results.sqlite` (rebuildable,
  superseded by the canonical store).

Note: the ring buffer bounds the *working tree*; **git history grows with each
committed run**. For routine smoke runs that's kilobytes; for coding runs with
large stdout logs it can be megabytes. Commit thoughtfully, or `prune`/`delete`
before committing if you don't want a run in history.

## The report tool (`scripts/gb-report.py`)

Static HTML report generation with an LLM-friendly contract:

```bash
gb-report --suite coding --view grid --narrative "..." --out coding-grid.html
gb-report --runs run-... --view failures --narrative "..." --out failures.html
gb-report --model glm52 --scenario coding.retry-policy --view cell --out cell.html
gb-report --suite orchestrator --view grid --narrative - --out grid.html  < narrative.md
```

The tool owns DB access + view dispatch + HTML writing; the caller (often an
LLM) decides what to report and supplies the prose narrative (dropped into the
report's lede). The HTML is a side effect the LLM never holds in context —
that's the token-efficiency win: a 50 KB report from a ~400-token turn.

### Views

Three views ship; each is a self-contained module under
`scripts/gb/report/views/`:

| View | Use |
|---|---|
| `grid` | Model × scenario pass/score matrix. The model-comparison workhorse. Click-through per cell. |
| `failures` | Failure-first triage, grouped by failure category, with the "why" + one click-through artifact per failure. |
| `cell` | One cell deep-dive: every scorer row (full detail), all embedded artifacts (patch + output + stdout), all representative samples. |

### Adding a view

Clean extension point — a view is a render function + one `register()` call:

```python
# scripts/gb/report/views/my_view.py
from . import ViewContext, ViewResult, register
from ..envelope import esc

def render(ctx: ViewContext) -> ViewResult:
    return ViewResult(title="My view", html=f"<p>{len(ctx.cells)} cells</p>")

register("my-view", "My view", "Description for --help", render)
```

The view reads from `ViewContext` (pre-fetched cells + a store connection for
lazy artifact/sample fetches). It never touches the filesystem or owns DB
queries directly. Add it to the import list in `views/__init__.py` and it
appears in `--view` choices automatically.

### Narrative slot

`--narrative` is the LLM's value-add, dropped into the report as the lede
(styled `<div class="narrative">`). Everything below it is structured evidence.
This is what makes the report *edited* rather than *dumped* — the LLM curates
the prose, the tool curates the data, neither does the other's job.

## When you need the raw files

Because files are now ring-buffered scratch space, deep history isn't on disk —
but you rarely need it. The DB holds the judgement + code samples; if you need
to poke at a specific old run's full tree, re-run the scenario:

```bash
gb-run.py --scenario coding.retry-policy --candidate pi-coding-glm52-den-router
```

Files regenerate, slightly non-deterministically (good enough — this isn't peer
review). For *current* runs (within the ring buffer), the files are right where
they always were.
