# HUD-Chaos Distractor-Resistance Vision Pattern (2026-06-26)

Use when evaluating visual-inspect models on noisy screenshots where the useful signal is a crisp UI/HUD around the borders and the center scene is deliberately distracting.

## Scenario shape

- Generate deterministic synthetic images first (PIL is enough) with:
  - central visual mess: particles, enemies/nameplates, damage numbers, small decoys, decorative text;
  - crisp border UI/HUD: health/shield/heat/ammo/objective/minimap/status/console panels;
  - exact manifest facts for all actionable UI text and values.
- Prompt should be task-shaped, not generic description-shaped:
  - ask for HUD/status extraction;
  - explicitly say not to inventory center combat/art unless it affects the status answer.
- Keep the existing `response_schema = "vision_description_v1"` contract so runner compatibility stays simple.

## Manifest fields

Add normal required fields:

```json
{
  "required_mentions": [
    {"id": "health_23", "aliases": ["HEALTH 23%", "health 23"], "region": "upper left", "importance": 4}
  ],
  "visible_text": [{"text": "HEALTH 23%", "strict": true}],
  "forbidden_claims": ["full health"],
  "relationship_expectations": [
    {"subject": "LOW HEALTH", "relation": "upper center", "object": "HUD"}
  ],
  "distractor_mentions": ["SKELETON", "DRONE", "CHAOS BOSS", "LOOT", "TARGET"]
}
```

`distractor_mentions` is optional and activates `distractor_resistance` detail in `vision-description-quality`. It measures whether the response repeated known center-noise terms. This should be reported as a separate focus column even if the overall score passes.

## Scoring guidance

- Recommended initial scenario parameters:
  - `target_concrete_items: 8`
  - `distractor_weight: 0.20`
  - `allowed_distractor_mentions: 1`
  - threshold `vision-description-quality: 0.75`
- Interpret columns separately:
  - required HUD coverage = can see/extract actionable UI facts;
  - distractor resistance/focus = can ignore visual mess;
  - schema compliance = can emit valid structured output.
- A strict-JSON 0.0 with useful raw content is a structured-output failure, not a visual-understanding failure.
- If pass/fail should mean “HUD-focused,” either increase `distractor_weight` or add a separate minimum focus threshold; otherwise keep pass/fail for HUD extraction and report focus separately.

## Verified GoblinBench example

Repo files:

- Generator: `scripts/vision-fixtures/generate_game_hud_prototypes.py`
- Fixtures: `fixtures/vision/chaotic/prototypes/game-hud-low-health-chaos.png`, `game-hud-overheat-chaos.png`
- Scenarios: `suites/vision/inspect-game-hud-low-health-chaos.json`, `inspect-game-hud-overheat-chaos.json`
- Report: `docs/vision-hud-chaos-distractor-matrix-2026-06-26.md`
- Den doc: `goblinbench/vision-hud-chaos-distractor-matrix-2026-06-26`

First 9-model run (`run-20260626-022642-df01eb2b`) showed the pattern is more discriminating than generic chaotic descriptions: parseable cells generally got full HUD coverage, but focus ranged from 1.0 to 0.0 depending on whether models repeated center decoys.
