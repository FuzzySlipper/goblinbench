# Environment provenance and comparison lanes

Every candidate result written by `gb-run.py` has an `environment` envelope. The
same envelope is embedded as `artifacts/environment.json` and stored in the
canonical SQLite database so reports do not need to reconstruct execution
conditions from candidate names or raw transcripts.

## Comparison lanes

- `model-core` measures a model through a direct model API without an agent
  environment being part of the treatment.
- `environment-realized` measures the model as experienced through an agent
  substrate, profile, prompt assembly, and tool configuration.

Reports keep these lanes separate. The grid view renders a section per lane and
keys cells by candidate, so two candidates using the same resolved model cannot
silently overwrite or merge one another. Use `gb-report.py --lane <lane>` to
filter deliberately.

## Envelope version 1

The stable top-level fields are:

- `schema_version`, `lane`, and `name`;
- `model`: requested/resolved model and provider, reasoning effort, redacted
  requested configuration, and its SHA-256;
- `substrate`: runner kind/name/version and transport-specific identity;
- `profile`: profile/revision/role, prompt assembly, and tool-catalog identity;
- `harness`: runner/scenario/fixture versions and copied-workspace SHA-256;
- `execution`: elapsed time, terminal states, retries, tool calls, and command
  cycles where the substrate exposes them;
- `usage`: input, cached-input, output, reasoning-output, and total tokens plus
  model context window when reported by the endpoint;
- `cost`: classification, optional amount/currency, and evidence basis;
- `outcome`: runner success and the primary scorer result.

Keys containing secret, token, password, API-key, or authorization material are
redacted before candidate configuration is retained.

## Honest cost classes

- `metered`: an endpoint supplied an attributable charge.
- `estimated`: an estimate with its basis recorded.
- `opaque-subscription`: the run used a subscription but no per-run charge was
  exposed.
- `unavailable`: no defensible cost information exists.

`opaque-subscription` and `unavailable` reject numeric amounts. Missing cost is
not treated as zero.

Rows imported from older run JSON remain queryable and are explicitly labeled
`model-core`, `legacy-unclassified`, and `unavailable`; they are not presented as
newly measured environment evidence.

## Compact comparison report

```bash
python3 scripts/gb-report.py --runs <run-id> --view environment \
  --out /tmp/goblinbench-environments.html
```

The report shows lane, environment, profile, exact resolved model, scenario,
outcome, elapsed time, token usage, and cost classification.
