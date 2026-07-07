# Qualitative comparison workflow

GoblinBench supports prose-heavy benchmark campaigns with `scripts/gb-qual-report.py`.
Use this when normal scoring is intentionally minimal and the useful artifact is a
side-by-side Markdown comparison plus a qualitative LLM judge ranking.

## Run shape

1. Add qualitative scenarios under `suites/qualitative/` (or another suite name).
   The existing `OpenAiChatRunner` handles plain `OpenAiModel` candidates.
2. Run the candidate matrix with the normal runner so raw outputs land in the
   canonical store:

   ```bash
   python3 scripts/gb-run.py --suite qualitative \
     --candidate den-router-minimax-fuzzy,den-router-stepfun-fuzzy
   ```

3. Iterate on the judge prompt without spending model calls:

   ```bash
   python3 scripts/gb-qual-report.py \
     --runs <run-id> \
     --suite qualitative \
     --dry-run \
     --campaign my-campaign-v1 \
     --judge-template templates/qualitative-judge-v1.md
   ```

   This writes:
   - `runs/qualitative/<campaign>/judge-template.md`
   - `runs/qualitative/<campaign>/rubric.md`
   - `runs/qualitative/<campaign>/judge-requests/<scenario>.md`
   - `runs/qualitative/<campaign>/qualitative-report.md`

4. Call a real judge model once the request packets look right:

   ```bash
   python3 scripts/gb-qual-report.py \
     --runs <run-id> \
     --suite qualitative \
     --campaign my-campaign-v1-judged \
     --judge-provider den-router \
     --judge-model minimax \
     --judge-template templates/qualitative-judge-v1.md \
     --out runs/qualitative/my-campaign-v1-judged/qualitative-report.md
   ```

   `--judge-candidate <id>` can be used instead of explicit judge provider/model.

## Prompt/rubric tweaking

- `--judge-template <path>` accepts these placeholders:
  - `{{scenario_id}}`
  - `{{scenario_name}}`
  - `{{scenario_prompt}}`
  - `{{rubric}}`
  - `{{outputs_markdown}}`
  - `{{outputs_json}}`
- `--rubric-file <path>` or `--rubric "..."` changes the rubric without editing the
  main judge template.
- `--max-output-chars N` controls per-candidate output truncation before judging.
- Labels are anonymized by default (`A`, `B`, `C`) to reduce brand bias; pass
  `--no-blind` when the judge prompt should see model ids.
- `--no-json-response-format` is available for OpenAI-compatible endpoints that
  reject `response_format={"type":"json_object"}`.
- `--judge-extra-json '{"temperature":1.0}'` (or similar) merges provider-specific
  knobs into the judge request; use this for models with unusual parameter
  constraints.

## Re-rendering from saved/manual judge output

For manual edits or replaying a saved judge response, put one file per scenario in
a directory named as `<scenario-id>.json`, `<scenario-id>.txt`, or
`<scenario-id>.raw.txt` after sanitization (for example
`qualitative.sample.json`) and run:

```bash
python3 scripts/gb-qual-report.py \
  --runs <run-id> \
  --suite qualitative \
  --judge-response-dir /path/to/responses \
  --campaign my-campaign-rerender
```

The report records the parsed judge rankings, raw responses, request packets,
prompt/rubric copies, and `judgements.json` under the campaign directory.

## Interpretation rules

Treat the LLM judge ranking as qualitative commentary, not ground truth. Report
runner failures separately from output quality, and inspect raw candidate outputs
and raw judge responses before drawing strong conclusions.
