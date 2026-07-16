# Visual-Inspect Deployed Gemma4 Tuning (2026-06-26)

Session-specific reference for making the deployed `visual-inspect` service on den-srv accept Gemma4 outputs reliably enough for service-level smoke tests.

## Context

- Service host: `den-srv` / `192.168.1.10`
- Unit: `den-go@visual-inspect.service`
- Local URL: `http://127.0.0.1:8089`
- Config: `/data/services/visual-inspect/config/config.yaml`
- Prompts: `/data/services/visual-inspect/prompts/`
- Model endpoint: Lemonade-compatible `http://192.168.1.23:13305/v1`
- Initial model: `Gemma-4-26B-A4B-it-GGUF`

## Failure mode

The deployed service returned HTTP 200 with `verdict: uncertain` and warning `model_output_invalid` for valid screenshot requests. Direct provider reproduction showed this was not a vision failure: Gemma4 read the HUD screenshot correctly, but emitted schema-wrong JSON such as:

- top-level `evaluations` instead of `criteria_results`;
- per-criterion `result` instead of `verdict`;
- observations as strings instead of objects;
- `regions` / `box_2d` instead of service `region` objects.

The service decoder is intentionally strict: JSON only, no fences, no unknown fields, exact Go DTO field names, and required arrays/objects.

## Debugging pattern

1. Verify service health and auth first:
   - `/health`, `/version`, `systemctl is-active den-go@visual-inspect.service`.
   - No bearer token should return 401; authenticated request should reach the model path.
2. Copy test screenshots under the service-owned artifact root, not `/tmp`:
   - `/data/services/visual-inspect/data/artifacts/...`
   - `PrivateTmp=true` means the service cannot see the caller's normal `/tmp`.
3. Run `/v1/visual-inspect/evaluate` through the service and record normalized result/warnings.
4. If `model_output_invalid`, reproduce the exact provider call directly against Lemonade/OpenAI-compatible API to inspect raw model text. The service may not log raw model output by design.
5. Compare raw output to `schemas/evaluate-response.schema.json` and the Go DTOs in `internal/schema/dto.go`.

## Tuning that worked

Config changes in `/data/services/visual-inspect/config/config.yaml`:

```yaml
llm:
  timeout: "90s"          # was 45s
  max_output_tokens: 4096 # was 2000
security:
  allow_unauthenticated_local_dev: false
```

Why: Gemma4 consumed substantial hidden/reasoning tokens; at `max_output_tokens: 2000` direct reproduction produced truncated JSON with `finish_reason: length`. At 4096, the same prompt produced parseable complete JSON.

Developer prompt changes in `/data/services/visual-inspect/prompts/visual-inspect.developer.md`:

- Add a compact strict JSON example with the exact top-level service shape:
  - `verdict`, `confidence`, `criteria_results`, `follow_up_hints`, `warnings`.
- Add field-name rules:
  - use `criteria_results`, not `evaluations`;
  - use `criterion_id`, not `id`;
  - use `verdict`, not `result`;
  - `observations` must be object arrays, not strings;
  - do not use `regions`, `box_2d`, `bbox`, `score`, or extra top-level fields;
  - omit `region` unless using `{x,y,width,height,coordinate_space:"image_pixels"}` exactly.
- Add fail-vs-uncertain guidance:
  - use `fail` when visible screenshot evidence clearly contradicts a criterion;
  - use `uncertain` only for missing/ambiguous/cropped/too-small/undecidable evidence;
  - confidence is confidence in the verdict, including confident failures.

## Verification after tuning

Authenticated service-level smokes passed:

- Low-health HUD positive: `verdict: pass`, all criteria pass, no warnings.
- Overheat HUD positive: `verdict: pass`, all criteria pass, no warnings.
- Negative low-health criteria (`HEALTH 100%`, `30 / 30`): `verdict: fail`, both criteria fail, no warnings.
- No-token request: HTTP 401 / `unauthorized`.

## Criteria authoring pitfall

Do not put meta-evaluation criteria into `visual-inspect` requests, e.g. “the result focuses on actionable HUD facts rather than center noise.” The service judges screenshot evidence, not another model's answer. Such criteria should be marked `uncertain` because no result text is visible. Use screenshot-visible criteria only.

## Operational hygiene

Before live edits, make timestamped backups under:

- `/data/services/visual-inspect/config/backups/`
- `/data/services/visual-inspect/prompts/backups/`

Restart and smoke after edits:

```bash
sudo systemctl restart den-go@visual-inspect.service
systemctl is-active den-go@visual-inspect.service
curl -fsS http://127.0.0.1:8089/health
```

Record the final service result packets or a concise summary in the relevant Den doc/task; do not embed raw screenshot bytes in Den messages.
