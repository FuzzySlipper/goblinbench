# Roleplay prose + instruction matrix (2026-07-08)

Session-specific reference for running GoblinBench SFW roleplay prose and no-user-control tests across the 15-model roleplay candidate matrix.

## What was run

Candidate split files:

- `candidates.roleplay-denrouter.json` — 11 den-router candidates.
- `candidates.roleplay-lemonade.json` — 4 Lemonade local candidates.

Suites:

- `roleplay-prose` — 7 SFW prose scenarios: rainy inn, orbital maintenance, train platform; minimal/v0/v1 anti-slop variants.
- `roleplay-instruction` — `no-user-control-reliquary-v0`, a strict agency/instruction-following probe.

Run IDs:

- Prose den-router: `run-20260707-211807-146e78c8` — 77/77 cells.
- Prose Lemonade: `run-20260707-211808-c1866247` — 28/28 cells.
- Instruction den-router: `run-20260707-222223-484bafea` — 11/11 cells.
- Instruction Lemonade: `run-20260707-214506-9c827b76` — 4/4 cells.

Judge artifacts:

- `runs/qualitative/roleplay-prose-grok-judge-20260708/qualitative-report.md`
- `runs/qualitative/roleplay-instruction-grok-judge-20260708/qualitative-report.md`
- `runs/qualitative/roleplay-prose-instruction-grok-judge-20260708/headline-summary.md`

Public page:

- `https://fuzzyslipper.github.io/den-web/roleplay-prose-instruction-2026-07-08/`

## Repeatable command pattern

Run deterministic smoke first:

```bash
python3 scripts/gb-run.py --suite roleplay-prose --candidate demo-noop
python3 scripts/gb-run.py --suite roleplay-instruction --candidate demo-noop
```

Run provider splits rather than one mixed slog:

```bash
python3 scripts/gb-run.py --suite roleplay-prose --candidates candidates.roleplay-denrouter.json
python3 scripts/gb-run.py --suite roleplay-prose --candidates candidates.roleplay-lemonade.json
python3 scripts/gb-run.py --suite roleplay-instruction --candidates candidates.roleplay-denrouter.json
python3 scripts/gb-run.py --suite roleplay-instruction --candidates candidates.roleplay-lemonade.json
```

Label important runs:

```bash
python3 scripts/gb-store.py label <run-id> "roleplay prose denrouter matrix YYYY-MM-DD"
```

Judge with Grok after the Kimi judge gotcha from the heat-boundary run:

```bash
python3 scripts/gb-qual-report.py \
  --runs <denrouter-run>,<lemonade-run> \
  --suite roleplay-prose \
  --campaign roleplay-prose-grok-judge-YYYYMMDD \
  --out runs/qualitative/roleplay-prose-grok-judge-YYYYMMDD/qualitative-report.md \
  --rubric-file templates/roleplay-judge-rubric-v1.md \
  --candidates candidates.roleplay-matrix.json \
  --judge-candidate denrouter-grok-roleplay \
  --judge-temperature 0.2 \
  --judge-timeout 300 \
  --judge-max-tokens 8192 \
  --max-output-chars 2800 \
  --no-blind
```

Publish summary-first page via den-web shared pages:

```bash
cd /home/dev/den-web
npm run publish:page -- \
  --title "Roleplay Prose + Instruction Matrix — YYYY-MM-DD" \
  --slug roleplay-prose-instruction-YYYY-MM-DD \
  --summary "GoblinBench SFW roleplay prose and no-user-control instruction-following matrix." \
  --source /home/dev/goblinbench/runs/qualitative/<campaign>/headline-summary.md \
  --source /home/dev/goblinbench/runs/qualitative/roleplay-prose-grok-judge-YYYYMMDD/qualitative-report.md \
  --source /home/dev/goblinbench/runs/qualitative/roleplay-instruction-grok-judge-YYYYMMDD/qualitative-report.md \
  --git-commit --git-push
```

## Observed interpretation pattern

- Prose quality and no-user-control are separate skills. In this run, DeepSeek Pro won prose aggregate but failed the strict no-user-control probe; Grok won no-user-control.
- For public reader summaries, lead with a short TL;DR, then compact aggregate table, then scenario winners, then caveats. Do not make readers dig through raw outputs first.
- Include explicit caveat: one model judge + small scenario sample + subjective roleplay taste.

## Grok 4.5 comparison note — 2026-07-09

When comparing `grok` vs `grok-4.5`, avoid too-small `--max-output-chars` in `gb-qual-report`: a 2800-char cap made the judge think full model outputs were truncated and unfairly penalized long Grok 4.5 generations. Re-run qualitative comparisons with `--max-output-chars 7000` or enough to include full outputs.

Full-context DeepSeek-Pro judge comparison artifacts:

- `runs/qualitative/grok45-vs-grok-roleplay-prose-fullctx-20260709/qualitative-report.md`
- `runs/qualitative/grok45-vs-grok-roleplay-instruction-fullctx-20260709/qualitative-report.md`

Outcome: `grok-4.5` beat old `grok` on all 7 SFW prose scenarios (avg score 8.43 vs 7.29) and the no-user-control instruction probe (9.0 vs 7.5). Both models passed heuristic scoring; the qualitative difference was stronger sensory specificity, subtext through objects/timing, and better roleplay openings. Caveat: one rainy-doorway baseline scenario still had hard user-character control for both models.

Latency changed materially: old `grok` prose averaged ~17s/cell; `grok-4.5` prose averaged ~60s/cell.

## Publishing gotcha fixed

`den-web` shared-page publisher originally overwrote duplicate source basenames when multiple artifacts were named `qualitative-report.md`. Fix added: duplicate names become `qualitative-report.html`, `qualitative-report-2.html`, etc., and source files mirror that suffix. Future report pages can safely include multiple artifacts from different campaign directories.
