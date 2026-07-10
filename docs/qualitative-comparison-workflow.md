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

## Plain chat candidate knobs for prose campaigns

Plain `OpenAiModel` candidates can use normal generation knobs plus a few
OpenAI-compatible/provider-specific controls in `config`:

```json
{
  "id": "lemonade-gemma4-26b-roleplay-thinking-high",
  "kind": "OpenAiModel",
  "model": "Gemma-4-26B-A4B-it-GGUF",
  "provider": "lemonade",
  "base_url": "http://192.168.1.23:13305/v1",
  "config": {
    "max_tokens": 8192,
    "reasoning_effort": "high",
    "include_temperature_with_reasoning_effort": true,
    "temperature": 0.85,
    "chat_template_kwargs": {"enable_thinking": true}
  }
}
```

Notes:
- `reasoning_effort` is sent as a top-level request field. By default the runner
  omits `temperature` when `reasoning_effort` is set because some reasoning
  endpoints reject the combination. Set `include_temperature_with_reasoning_effort`
  to `true` when the endpoint accepts both and prose sampling still matters.
- `chat_template_kwargs` is sent as a top-level request field for local servers
  such as Lemonade/llama.cpp. Gemma 4 26B via Lemonade emitted only
  `reasoning_content` until `chat_template_kwargs.enable_thinking=false` was set;
  use `true` plus a large `max_tokens` when explicitly testing thinking mode.
- `request_overrides` still exists as an escape hatch and is applied last, so it
  can override any first-class field above for a specific experiment.
- Long-thinking roleplay tests should set permissive scenario timeouts, e.g.
  `"timeout_seconds": 900`, and a large response budget (`max_tokens` 8192+).
  The qualitative report includes output chars, reasoning chars, and finish
  reason in the candidate table when the endpoint returns them.

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

## Adult-romance / heat-boundary probes

For romance-model fit, prefer a simple ladder over clever prompt incantations:

1. PG-13 romance: attraction, kissing, closeness; no explicit sexual acts.
2. R soft-focus: sensual bedroom escalation, undressing/touch, no graphic anatomy.
3. NC-17 explicit: direct on-page adult sexual content between consenting adults.
4. NC-17 + no-user-control: same boundary pressure plus strict player agency.

The goal is not to bypass filters. Make the setup boringly unambiguous: fictional,
private, consenting adults, sober, unrelated, no coercion, no age ambiguity, and no
request to roleplay a real person. Tell the model to plainly refuse if that tier is
outside its safety rules. This quickly separates models whose dial stops at PG-13,
soft R, explicit NC-17, or refusal.

Use `templates/roleplay-heat-boundary-judge-rubric-v1.md` only for fallback
classification, not prose-quality judging. A judge does not necessarily need to be
as permissive as the generator if it only classifies boundary behavior, but
input-side filters may still reject raw explicit candidate outputs. For filtered
judges, ask for classification only, quote minimally, or pre-redact explicit
anatomical terms. The built-in `roleplay-heat-boundary` scorer is the preferred
first pass because it never asks a model to evaluate erotica quality.

## Interpretation rules

Treat the LLM judge ranking as qualitative commentary, not ground truth. Report
runner failures separately from output quality, and inspect raw candidate outputs
and raw judge responses before drawing strong conclusions.
