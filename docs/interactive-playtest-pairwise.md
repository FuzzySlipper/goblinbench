# GoblinBench interactive playtest pairwise campaign

The `interactive-playtest` suite is a small decision corpus, not a general
model leaderboard. Luna at the configured playtester effort is the incumbent;
run one prequalified challenger at a time against the same scenario, target
revision, browser manifest, viewport, restricted `vision_playtester` profile,
mission, and budgets.

## Preconditions

The candidate must resolve to an active Rusty Crew profile with image input,
multi-turn tool calls, and the four `vision_playtester` operations. Its config
must retain a `prequalification` object with an evidence reference and true
checks for image input, multi-turn tools, the restricted profile, lifecycle
cleanup, and provider/model identity readback. The runner
uses only the debug service at `http://127.0.0.1:9348` and creates a disposable
native profile/session. The target repository must be a clean worktree whose
current `HEAD` equals the
scenario's full expected SHA. A stale checkout is an infrastructure failure,
not a model result.

Set the target once for a campaign:

```bash
export GOBLINBENCH_PLAYTEST_REPO_ROOT=/home/dev/rusty-craftsurvive
export GOBLINBENCH_PLAYTEST_REVISION=4d03873ac6cc756ae21906a493d457c4b016be3a
```

For a mutation cell, point the same runner at its immutable mutation worktree
and set the cell's exact revision and proof before running that cell:

```bash
export GOBLINBENCH_PLAYTEST_REPO_ROOT=/path/to/inverted-mouse-look-worktree
export GOBLINBENCH_PLAYTEST_MUTATION_REVISION=<40-character-mutation-sha>
export GOBLINBENCH_PLAYTEST_MUTATION_PROOF='mutation commit plus deterministic product-test command'
export GOBLINBENCH_PLAYTEST_MUTATION_PROOF_PATH=/path/to/retained-mutation-proof.txt
```

The checked-in scenarios deliberately reject a mutation run when these
scorer-side proof inputs are absent; GoblinBench does not invent or expose a
mutation identity to the worker.

Create those worktrees from the maintained mutation patches rather than
editing a product checkout in place:

```bash
python3 scripts/gb/prepare_playtest_mutations.py \
  --repo-root /home/dev/rusty-craftsurvive \
  --base-revision 4d03873ac6cc756ae21906a493d457c4b016be3a \
  --output-root /home/dev \
  --proof-root /home/dev/goblinbench/docs/evidence/interactive-playtest/mutations
```

The command refuses a dirty or stale baseline, applies one audited patch per
worktree, commits it at an exact detached SHA, runs its source contract, and
prints the scorer-side `mutation_revision`, `worktree`, and
`mutation_proof_path`. Run the CraftSurvive browser smoke on each generated
clean worktree and append its retained output to the corresponding proof
record before admitting the cell. The `/home/dev` output root is intentional:
the generated directories sit beside `/home/dev/rusty-engine`, preserving
CraftSurvive's sibling Cargo path dependency. Keep these worktrees outside
GoblinBench's ring-buffered `runs/run-*` directories.

The example candidate file is intentionally separate from the default matrix:

```bash
python3 scripts/gb-run.py \
  --candidates candidates.interactive-playtest.example.json \
  --suite interactive-playtest \
  --candidate goblinbench-luna-vision-playtester,goblinbench-challenger-vision-playtester \
  --label "Luna versus one prequalified challenger"
```

The same candidate pair must be used for every case in a campaign. Do not add
many models to a matrix just to obtain an abstract score.

## Evidence and adjudication

`playtest-evidence` is a contract scorer. It checks the exact revision binding,
restricted profile identity, allowed tool catalog, terminal outcome, retained
`playtest-index.json`, screenshots/frame artifacts, and observation sequences
for motion/transition claims. A screenshot alone cannot pass a transition
claim. It emits no scalar strength score.

After both cells in a `pair_id` have been collected, `gb-run.py` attaches one
of these labels to each cell and writes `pairwise.json`:

- `challenger_win`
- `luna_win`
- `tie`
- `invalid_pair`

The deterministic corpus uses `expected_outcome` only to distinguish a correct
behavioral report from an incorrect one. If semantic judgment is needed, keep
the rubric, blinded inputs/outputs, and rationale as retained artifacts; do
not silently convert that judgment into an abstract score.

Selected indexes and referenced screenshots are copied to
`runs/evidence-archive/<sha256>/`, outside the `runs/run-*` ring buffer. The
canonical DB still receives the run, scores, and compact playtest artifacts.

## Reporting

```bash
python3 scripts/gb-report.py --suite interactive-playtest \
  --view playtest-pairwise --embed none \
  --narrative "Relational comparison of the challenger with the Luna incumbent." \
  --out /tmp/goblinbench-playtest-pairwise.html
```

The report has no score column. Inspect the archive path for disputed pairs and
keep `invalid_pair` separate from a genuine tie.
