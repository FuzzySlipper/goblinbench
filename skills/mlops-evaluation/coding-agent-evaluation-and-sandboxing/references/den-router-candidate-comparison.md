# Den router model comparison (cloud-via-127.0.0.1:18082)

Companion to `openai-mcp-tool-runner-and-local-model-comparison.md`. Covers
the cloud-via-den-router candidate case: candidate config layout, smoke
testing `/v1/models` listings before adding to `candidates.json`,
reasoning-token budgeting, and the A/B hinted suite run pattern that
already exists.

## Candidate config layout for den-router models

For candidates that route through the den router
(`http://127.0.0.1:18082/v1`), the relevant fields live at the candidate
root, not inside `config`. Working example from `candidates.json`:

```json
{
  "id": "den-router-deepseek-flash-tool-behavior",
  "kind": "OpenAiModel",
  "model": "deepseek-flash",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "api_key": "<redacted>",
  "cli_command": "mcp-openai-tool-use",
  "config": {
    "runner": "mcp-openai-tool-use",
    "temperature": 0.2,
    "max_tokens": 4096,
    "max_tool_rounds": 6
  }
}
```

Notes:

- `base_url` and `api_key` are at the root, not under `config`. The
  `OpenAiMcpSessionRunner` reads `candidate.BaseUrl ?? candidate.Endpoint`
  for the URL and `candidate.ApiKey` (or `config.api_key_env`) for the
  key. Putting them under `config` is silently ignored.
- The runner's per-model config knobs (`temperature`, `max_tokens`,
  `max_tool_rounds`) all live under `config`.
- The den router does not require a real key for models that proxy
  upstream; a placeholder is usually accepted. If the upstream
  demands auth, set `config.api_key_env` to an env var the runner
  resolves via `Environment.GetEnvironmentVariable`.

## Smoke test before adding a model from `/v1/models`

`GET /v1/models` returns the full catalog the den router is willing to
**route** to upstream providers, but it is **not** the same as "this
model will answer `chat/completions` successfully." Several user-named
models have been observed returning 404 from upstream even though they
are listed.

Smoke probe (a few seconds per model):

```bash
for m in glm kimi mimo nemotron stepfun hy3 minimax; do
  echo "=== $m ==="
  curl -sS -i -X POST http://127.0.0.1:18082/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"PONG\"}],\"max_tokens\":16}" \
    --max-time 30 | head -5
done
```

Interpret the response shape, not just the status:

| Signal | Meaning |
|---|---|
| `HTTP/1.1 200 OK` + non-empty `choices[0].message.content` | Working |
| `HTTP/1.1 200 OK` + empty `content` but non-empty `reasoning_content` | Reasoning model; `max_tokens` exhausted on internal reasoning. Increase `max_tokens` or use a non-reasoning variant. |
| `HTTP/1.1 404 Not Found` + body `{"timestamp":...,"path":"/v4/v1/chat/completions"}` | Den router has no route to that upstream provider |
| `HTTP/1.1 404 Not Found` + HTML body | Often an unrelated dev page; check `Access-Control-Allow-Headers` for the OpenRouter-style upstream signature |
| `HTTP/1.1 404 Not Found` + **empty body** (`Content-Length: 0`, `acw_tc` Alibaba Cloud WAF cookie) | **Model was once active but is now dead upstream.** The den-router still lists it in `/v1/models` but cannot route to it. Same pattern observed for both stepfun and nemotron. Do not schedule runs — re-check in a few days or try a different model. |

Observed current state (re-verify before trusting — model availability
changes frequently; confirmed alive at last check; dead models listed below
may reappear if upstream re-adds them):

| Model | HTTP | Type | Notes |
|---|---|---|---|
| `deepseek-flash` | 200 | Standard | Good baseline; no reasoning overhead |
| `deepseek-pro` | 200 | Reasoning | Burns reasoning tokens; budget `max_tokens >= 8192` |
| `kimi` (k2.6) | 200 | Reasoning | **Requires `temperature: 1.0`** — HTTP 400 with any other value |
| `kimi-code` (k2.7-code) | 200 | Coding/reasoning | New Moonshot coding model; smoke response reports upstream `kimi-k2.7-code`. **Requires `temperature: 1.0`** — HTTP 400 with `temperature: 0.2`. Initial 2026-06-13 matrix hit transient `HTTP 429: engine overloaded`; 2026-06-16 rerun after hosting fix had no provider 429s and coding improved materially. See `references/kimi-code-glm52-benchmark-2026-06-16.md`. |
| `mimo` (v2.5) | 200 | Reasoning | Burns reasoning tokens; budget `max_tokens >= 8192` |
| `mimo-pro` (v2.5-pro) | 200 | Reasoning | Burns reasoning tokens |
| `minimax` (M3) | 200 | Reasoning | Burns reasoning tokens; slow (~35s/scenario avg). **Rate-limited** (Token Plan Plus, 5-hour rolling window); 429s when exhausted. Check before scheduling matrix runs. |
| `glm` (5.1) | 200 | Reasoning | Burns reasoning tokens; budget `max_tokens >= 8192` |
| `glm52` (GLM 5.2) | 200 | Reasoning | Routes to upstream `glm-5.2`. Smoke with `max_tokens:64` can finish `length` with empty content after reasoning; use generous `max_tokens` (8192 in benchmark). Strong all-rounder in 2026-06-16 run; see `references/kimi-code-glm52-benchmark-2026-06-16.md`. |
| `nemotron` | 404 | **Dead** | Was standard/no-reasoning via OpenRouter; removed from upstream ~2026-06-10 ("The model 'nemotron' does not exist.") |
| `stepfun` (Step 3.7 Flash) | 200 | Standard | Routes via OpenRouter; **SSE-whitespace-prefixed JSON** (see below). **⚠️ Routing state changes mid-day.** As of 2026-06-10 it returned empty-body 404 (dead), then came back to 200 after a den-router config change. Re-smoke before any fresh matrix run; do not depend on yesterday's status. |
| `hy3` (Tencent HY3 Preview) | 200/429 | Standard | Routes via SiliconFlow via OpenRouter; **SSE-whitespace-prefixed JSON**. Subject to rate-limiting (429) under load. |
| `gpt` (via OpenRouter) | 200 | Standard | Strong performer on ambiguity suite (5/6 hinted); good SOTA baseline |
| `grok` | 200 | Standard | Solid mid-range; handles clarify-destructive well with hints |
| `qwenplus` | 200 | Standard | Weak on coding (1/6), weak on MCP (1/6) |
| `qwenmax` | 200 | Standard | Best coding performer observed (6/6); strong MCP |
| `nex-n2-pro` | 200 | Reasoning | **Runner errors** — some responses omit `choices[0].message`, causing runner failures. Slow (~3min/run). Burns reasoning tokens. |
| `deepseek` (base) | 200* | **Broken** | Returns completely empty responses (content + reasoning both empty). Do not use. |
| `codex-pi` | 404 | **Dead** | Routes to chatgpt.com OAuth profile; not a chat/completions endpoint |

\* `deepseek` base returns HTTP 200 but with zero-length content and no
`reasoning_content` — functionally unusable.

### SSE-whitespace response quirk (hy3; stepfun when it was alive)

Some OpenRouter-proxied models (`hy3`, and formerly `stepfun`) returned HTTP 200 with
JSON bodies prefixed by SSE-style whitespace (`\n         \n\n`). Standard
`json.loads(response_text)` fails because of the leading whitespace and
newlines. Strip to the first `{` before parsing:

```python
start = raw_response.find('{')
data = json.loads(raw_response[start:])
```

This does not affect the GoblinBench runner (which uses
`System.Text.Json` with stream reading), but will break ad-hoc `curl |
python3 -c "import sys,json; ..."` smoke probes unless handled.

Add only verified models to `candidates.json`; do not copy names from
`/v1/models` blindly. The smoke probe with `max_tokens:16` is necessary
but not sufficient — some models (notably kimi) accept low-effort probes
at any temperature but reject real tool-use requests with non-1.0
temperature.

### Smoke-probe pitfall: shell quoting with `curl -d` inline JSON

When running smoke probes from scripts or `execute_code`, do **not**
interpolate JSON directly into `curl -d '...'` — shell quoting will
silently mangle the payload, and `curl` returns HTTP 200 with valid but
wrong JSON (e.g. `{"error":{"message":"..."}}`). A naive `json.loads()`
then falls into the `choices` path and reports empty content instead
of the actual error.

**The fix:** write the JSON payload to a temp file, then `curl -d @tmpfile`:

```python
import tempfile, json, os

payload = {"model": model, "messages": [...], "max_tokens": 200}
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    json.dump(payload, f)
    tmpf = f.name

r = os.popen(f'curl -s -m 30 -X POST http://127.0.0.1:18082/v1/chat/completions '
             f'-H "Content-Type: application/json" -d @{tmpf}').read()
os.unlink(tmpf)

resp = json.loads(r)
if "error" in resp:
    print(f"FAIL: {resp['error']['message']}")
```

**Always check for `"error"` in the response** before accessing `choices[0]`.

## Model-specific parameter constraints

Some den-router upstream models reject parameters that the OpenAI API
normally accepts:

- **`kimi` and `kimi-code` require `temperature: 1.0` exactly.** Setting any other value
  (including the common default of 0.2) produces `HTTP 400: invalid
  temperature: only 1 is allowed for this model`. This does not surface
  in the basic smoke probe (which may not send temperature at all). Set
  `temperature: 1.0` in the candidate config for kimi-family models; do not use the
  generic 0.2 default.

When adding a new den-router model, after the initial smoke probe, do a
second probe that includes `temperature` to check for model-specific
constraints:

```bash
curl -sS -X POST http://127.0.0.1:18082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"NEW_MODEL","messages":[{"role":"user","content":"OK"}],"max_tokens":16,"temperature":0.2}' \
  --max-time 30
```

## Reasoning-model token budgeting

`kimi` and `mimo` (and any future reasoning model exposed through the
router) emit internal `reasoning_content` before any tool call. Two
practical implications:

1. **`max_tokens` is the total ceiling for reasoning + answer +
   tool-call arguments.** `max_tokens: 1024` is too low; reasoning
   consumes the budget before the model produces visible output.
   `max_tokens: 4096` is the working minimum for tool-use suites.
2. **No automated guard in the runner.** The scorer sees
   `finish_reason: "length"` and an empty `content`; this currently
   scores as "no tool calls" rather than "ran out of budget." If
   comparing reasoning and non-reasoning models, either normalize
   `max_tokens` high enough to give the reasoning model a fair chance
   or record `max_tokens` and `finish_reason` in the result so the
   comparison is interpretable.

Future: extend the OpenAI tool runner to surface
`reasoning_content` and `finish_reason` in the chat transcript
artifact so the scorer can treat `finish_reason: "length"` distinctly
from "model refused to call tools."

## A/B hinted suite pattern (already wired)

`suites/den-mcp-ambiguity-hinted/` already exists as a parallel to
`suites/den-mcp-ambiguity/`. Same scenarios, same prompts, same
scoring — only the tool descriptions and selected `project_id` schema
fields differ (appended `TOOL HINT:` blocks). Scenarios carry
`tool_description_variant: "baseline" | "hinted"` and the
`ReportGenerator` already tags hinted runs as
`tool-description-hints` so reports can be filtered.

Regenerate both variants from the pinned catalog:

```bash
python3 scripts/generate-den-mcp-ambiguity-suite.py --variant baseline
python3 scripts/generate-den-mcp-ambiguity-suite.py --variant hinted
```

Run pattern for an A/B comparison against N den-router models:

```bash
RUN_IDS=()
for variant in baseline hinted; do
  for cand in den-router-glm-tool-behavior \
              den-router-kimi-tool-behavior \
              den-router-mimo-tool-behavior \
              den-router-nemotron-tool-behavior \
              den-router-stepfun-tool-behavior \
              den-router-hy3-tool-behavior \
              den-router-minimax-tool-behavior; do
    run_id=$(dotnet run --no-restore --project src/GoblinBench.Runner -- \
      --suite den-mcp-ambiguity${variant:+-$variant} \
      --candidate "$cand" 2>&1 \
      | grep -oE 'run-[0-9]{8}-[0-9]{6}-[a-z0-9]+' | head -1)
    RUN_IDS+=("$run_id")
  done
done
```

Generate separate reports per variant — `--suite` only matches the
exact suite prefix:

```bash
# Baseline: suite IDs start with "den-mcp-ambiguity."
dotnet run --no-restore --project src/GoblinBench.Runner -- report \
  BASELINE_RUN_IDS... \
  --suite den-mcp-ambiguity \
  --output runs/den-mcp-ambiguity-report/baseline-report.md

# Hinted: suite IDs start with "den-mcp-ambiguity-hinted."
dotnet run --no-restore --project src/GoblinBench.Runner -- report \
  HINTED_RUN_IDS... \
  --suite den-mcp-ambiguity-hinted \
  --output runs/den-mcp-ambiguity-report/hinted-report.md
```

Candidate IDs are identical across variants, so passing all run IDs to a
single `--suite den-mcp-ambiguity` report will include only baseline
runs and silently drop hinted ones. To compare, load both JSON reports
and compute per-(scenario, candidate) deltas externally.

Suggested follow-on extension: mirror the same A/B pattern over
`mcp-tools/` (not just `den-mcp-ambiguity/`). The interesting
contrast for `mcp-tools` would be: same `dodgy-roster-lookup` and
`conflicting-tool-descriptions` prompts, with the hinted variant
cleaning up the tool descriptions — measuring "how much does good
naming/description help, and is the help model-dependent?"

## Discriminating the scorer

With 8/8 baseline-pass on the orchestrator suite and easy-model
saturating on `mcp-tools`, raw pass-rate is no longer the only signal
worth tracking. Per-scenario sub-metrics already exposed by
`McpToolUseScorer` are useful for "is this model failing because it
can't pick the right tool, or because it picks correctly but for
the wrong reason":

- `expected_call_count`, `matched_call_count`, `argument_match_count`
- `bypass_attempt_count` (hard-fail if `allow_bypass: false`)
- `forbidden_tool_used`
- `final_response_match_count` vs `final_response_expected_count`
- `clarification` sub-metrics (disallowed/required)
- `optional_metrics.Violated`, `recovery_metrics.RecoveredAfterError`

When reporting A/B results, surface the sub-metric delta per
(model, scenario) — not just the aggregate score.

## Orchestrator-suite runner pattern (den-router)

The `orchestrator` scenarios are pure decision-making prompts — they have
`available_actions` and context, but **no `fake_mcp.tools`**. The
`OpenAiMcpToolUseRunner` rejects these at construction with:

> "MCP tool-use scenario has no input.fake_mcp.tools entries."

**Do not run orchestrator scenarios through MCP-focused candidates.**

Create a separate "orchestrator" candidate entry that lacks `cli_command:
mcp-openai-tool-use` and has no `config.runner` override. Without those
fields, the runner selection falls through to `OpenAiChatRunner` (line 38:
`CanHandle` returns true for any `CandidateKind == OpenAiModel`), which
handles plain chat without fake tools.

Example orchestrator-safe candidate entries added to `candidates.json`:

```json
{
  "id": "den-router-stepfun-orchestrator",
  "name": "Den Router StepFun — orchestrator / decision-making",
  "kind": "OpenAiModel",
  "model": "stepfun",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "config": {
    "temperature": 0.2,
    "max_tokens": 4096
  }
},
{
  "id": "den-router-kimi-orchestrator",
  "name": "Den Router Kimi — orchestrator / decision-making",
  "kind": "OpenAiModel",
  "model": "kimi",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "config": {
    "temperature": 1.0,
    "max_tokens": 8192
  }
}
```

Key differences from MCP candidates:
- **No `cli_command`** — defaults to plain OpenAI chat.
- **No `config.runner`** — `OpenAiChatRunner` handles it.
- **No `max_tool_rounds`** — not applicable for non-tool scenarios.
- **Same `base_url`, `provider`, `model`** — identical den-router routing.

When the same model is needed for both MCP-tool-use and orchestrator
suites, create two entries (suffixed `-tool-behavior` and `-orchestrator`)
rather than reusing one across suite types.

## Intermittent upstream failures during matrix runs

Large matrix runs (6+ candidates × 2 variants = 12+ runs) frequently hit
intermittent upstream failures. Observed patterns:

- **DeepSeek upstream 502s** ("All backends failed") — transient, resolves
  on rerun within minutes. Affects deepseek-flash, deepseek-pro.
- **Connection refused** (127.0.0.1:18082) — den-router briefly unavailable,
  usually between runs. Mid-run connection refused means the scenario scores
  0.25 (no tool calls) rather than failing cleanly.
- **nex-n2-pro response parsing** — OpenRouter-proxied responses sometimes
  omit `choices[0].message` entirely, causing "OpenAI-compatible response did
  not include choices[0].message" runner errors on ~4/6 scenarios. Likely a
  streaming framing issue. Reruns sometimes succeed.

**Recovery pattern:** After a matrix run completes, check each run.json for
non-empty `error` fields on candidate_results. Re-run only the affected
(candidate, variant) pairs. Do not re-run the entire matrix.

## Multi-round A/B merge analysis

When running models across multiple rounds (e.g. round 1: 6 models, round 2:
4 models, round 3: 3 models), generate separate baseline and hinted reports
per round, then merge in Python:

```python
bl = {}
hi = {}
all_cands = []
for bl_path, hi_path in round_report_pairs:
    bl_r = load_report(bl_path)
    hi_r = load_report(hi_path)
    bl.update(build_lookup(bl_r))
    hi.update(build_lookup(hi_r))
    all_cands.extend([c['candidate_id'] for c in bl_r['candidates']])
# Now bl[(scenario_short, candidate_id)] and hi[(...)] give scores
```

Sort by hinted pass count descending to produce the final leaderboard.

## Reasoning effort config support

The `OpenAiMcpToolUseRunner.BuildRequestBody` supports an optional
`reasoning_effort` config field. When set, it sends `reasoning_effort`
instead of `temperature` (some reasoning models reject temperature != 1
when reasoning_effort is present). When absent, it sends `temperature` as
before.

Candidate config for reasoning-effort variants:

```json
{
  "id": "den-router-deepseek-pro-tool-behavior-re-low",
  "kind": "OpenAiModel",
  "model": "deepseek-pro",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "cli_command": "mcp-openai-tool-use",
  "config": {
    "runner": "mcp-openai-tool-use",
    "reasoning_effort": "low",
    "max_tokens": 8192,
    "max_tool_rounds": 6
  }
}
```

Known values: `"low"`, `"medium"` (default), `"high"`. Not all upstream
providers honor the parameter — some silently ignore it — but none reject
it outright.

### Reasoning effort findings (2026-06-10)

Tested 7 models at `low` effort + deepseek-pro at `high` on the
`den-mcp-ambiguity` suite (6 scenarios × baseline + hinted):

- **Low effort is generally neutral-to-slightly-negative for tool
  discipline.** Most models don't move more than ±1 pass. StepFun and
  DeepSeek-Pro each lost 1 pass at low effort.
- **DeepSeek-Pro shows a clean monotonic improvement with more reasoning**
  on baseline (no hints): 1/6 default → 3/6 low → 4/6 high.
- **DeepSeek-Flash *gains* `clarify-destructive-doc-action` at low effort**
  (0.00→1.00) — the model that thinks less is the one that asks for
  clarification instead of acting. This supports "less thinking = more
  restraint" for non-reasoning models.
- **The `den-mcp-doc-system-planner` wall is untouched** at any effort
  level. More thinking does not help with the "den system planner" routing
  trap.
- **Practical takeaway:** Reasoning effort is a minor knob compared to
  hints. The difference between low and default is ±1 pass; the difference
  between baseline and hinted is 2-3 passes. Tool description quality
  matters more than inference compute for tool-discipline tasks.

## SOTA model behavior on the ambiguity suite

Testing Opus 4.8 and GPT (via OpenRouter) revealed an important pattern:

- **GPT leads at 5/6 hinted** — the best score observed on this suite.
  Only `den-mcp-doc-system-planner` remains unsolved.
- **Opus 4.8 scores only 3/6 hinted** — it over-acts on
  `clarify-destructive-doc-action` (takes action instead of asking for
  clarification) despite being the most capable model tested. The pattern:
  models trained to *be* the system (Opus) rather than *use* the system
  tend to overreach when placed inside a tool framework.
- **StepFun (Step 3.7 Flash) ties DeepSeek-Pro at 4/6 hinted** despite
  being likely the cheapest model in the field. Strong tool discipline
  at low cost makes it a compelling orchestrator candidate.
  **⚠️ StepFun is currently returning 404/dead on den-router (2026-06-10
  onward).** The historical benchmark data remains valid but you cannot
  run new stepfun evaluations right now. If it comes back, re-verify
  via smoke probe before scheduling runs.
- **Cost-per-pass insight:** StepFun at 4/6 for cents vs Opus at 3/6 for
  dollars suggests tool discipline is orthogonal to raw capability, and
  cheaper models can outperform SOTA on restraint/framework-fit tasks.

## Open gaps to fill when extending the router-side comparison

- No "delta" report mode in `ReportGenerator` yet. Currently you have
  to load both baseline and hinted reports and diff them in your
  head. A delta view that groups scenarios by base id and shows
  per-(model, variant) score deltas would be a small change with
  high payoff.
- No reasoning-vs-non-reasoning normalization helper. If you want to
  compare `kimi` and `deepseek-flash` fairly, the runner should
  either give both enough `max_tokens` to think or disable reasoning
  on the reasoning model via a config flag.
- No automated smoke probe in the runner. A pre-run check that
  POSTs to `/v1/chat/completions` with `max_tokens: 4` and refuses
  to schedule the candidate on a 404 would prevent the "ran 6
  scenarios, all 6 timed out because the model doesn't exist"
  failure mode.
