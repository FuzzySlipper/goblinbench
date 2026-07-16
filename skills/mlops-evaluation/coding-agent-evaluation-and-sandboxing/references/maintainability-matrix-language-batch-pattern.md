# Maintainability Matrix Language-Batch Pattern

Use this when running the Maintainability Mini-Service probes across many den-router/pi coding candidates.

## Reusable pattern

Prefer **one language at a time, candidates sequential within each language** for pi coding-agent matrices:

- The pi coding-agent candidates share sandbox/runtime/workspace plumbing.
- Sequential language batches avoid workspace collisions and keep failures attributable to one fixture language at a time.
- A full matrix can still run unattended via a wrapper script that launches one `gb-run.py` invocation per scenario and imports each completed run into `runs/goblinbench.sqlite`.

Recommended wrapper behavior:

1. Define explicit scenario IDs, e.g. Python/TypeScript/Go/Rust maintainability mini-service scenarios.
2. Define explicit candidate IDs in the intended comparison order.
3. For each scenario:
   - run `python3 scripts/gb-run.py --suite coding --scenario <scenario> --candidate <comma-separated candidates>`
   - save stdout/stderr to `runs/maintainability-matrix-logs/<scenario>-<run-id>.log`
   - parse `Run ID:` from output
   - import `runs/<run-id>/run.json` with `python3 scripts/gb-store.py import --run-json ...`
   - update a compact JSON summary file after every batch so progress survives interruption/compaction.
4. Start the wrapper with `terminal(background=true, notify_on_complete=true)` for a long matrix.
5. During progress checks, inspect the process tree to identify the active candidate/language instead of killing slow reasoning-model runs.

## Candidate/model ID gotcha

Do not assume friendly candidate names match current den-router IDs. Before a matrix:

- Check `candidates.json` for coding-agent candidates (`kind: CodingAgent`).
- Query `/v1/models` or otherwise verify exact routed IDs.
- Add fresh pi coding candidates for exact current router IDs rather than relying on stale aliases.

Observed durable example:

- Router exposed `qwen-max`, while an older coding candidate used `qwenmax`.
- Router exposed `kimi-code`, but there was no pi coding-agent candidate yet.
- Adding exact-ID candidates (`pi-coding-qwen-max-den-router`, `pi-coding-kimi-code-den-router`) avoided a matrix run with stale/non-routable model names.

## Smoke probes before spending model time

Before launching the matrix, do cheap direct OpenAI-compatible probes against `http://127.0.0.1:18082/v1/chat/completions` for each model ID. Treat HTTP OK as routability only; model output may be empty for very small `max_tokens` if reasoning content consumes the budget.

For Kimi-family models, include an explicit `temperature: 1.0` in at least one smoke probe to catch the known temperature constraint before scheduling expensive runs. If pi later fails with parameter rejection, patch the provider/candidate rather than calling it a model-quality failure.

## Reporting

Keep result tables flat and split:

- substrate/run status
- behavior tests (`passed/total`)
- duration
- maintainability signal (`changed_files`, central/max change share, largest function delta, handler max LOC)

This makes “all models solved it but wrote different-shaped code” visible without burying the style signal in prose.

## Scorer hygiene

For non-root fixtures, ensure `structure-metrics` honors scenario `scan_dir`. If a row unexpectedly counts integration tests or helper files as implementation files, verify `scripts/scorers/structure-metrics.py` and rescore/import the affected run artifacts before interpreting style rows.
