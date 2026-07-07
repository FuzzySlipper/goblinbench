# Vision Chaotic Image Description Test Design

Status: draft design for task #3425 follow-up. The chaotic-description requirements have been attached to Den task #3425. Source service contract: `den-services/visual-inspect-service-design-3317`.

## Goal

Add a more nebulous but useful vision-evaluation dimension: whether a model makes a serious attempt to describe a complicated / chaotic image instead of returning a vague, deceptive, overconfident, or generic description.

This complements more direct list/count/localization scenarios. The intended model-search use case is finding cheaper models with unusually strong visual understanding, especially for messy screenshots or dense scenes where a useful agent needs enough situational awareness to decide what to inspect next.

## Existing harness context

Current GoblinBench vision stack:

- `scripts/gb/runners/vision.py`
  - `cli_command = "vision-openai"`
  - Sends `scenario.input.image_paths` as OpenAI-compatible multimodal message parts.
  - Current default system prompt forces a UI-oriented JSON schema:
    - `elements_found`
    - `answer`
    - `confidence`
    - `hallucination_risk`
    - `suggested_action`
    - `actionability`
- `scripts/gb/scorers/vision_correctness.py`
  - Good for binary/UI element scenarios.
  - Not enough for dense scene description quality.
- `fixtures/vision/`
  - Currently minimal synthetic UI PNGs for smoke tests.

For chaotic description tests, keep the structured-output approach but use a scenario-specific schema/scorer rather than overloading `elements_found` too hard.

## Proposed scenario output schema

Add a new scorer/runner mode for description-rich vision scenarios. The model should return JSON such as:

```json
{
  "scene_summary": "one or two sentence overview",
  "salient_regions": [
    {"region": "upper left", "description": "..."},
    {"region": "center", "description": "..."}
  ],
  "objects_and_entities": [
    {"label": "red mug", "location": "lower right", "attributes": ["red", "partly occluded"]}
  ],
  "relationships": [
    "the red mug is partly behind the notebook",
    "the warning dialog overlaps the chart"
  ],
  "text_observed": ["visible text snippets, if any"],
  "uncertainties": ["things the model is unsure about"],
  "answer": "direct answer to the scenario prompt",
  "confidence": 0.0,
  "hallucination_risk": "low|medium|high"
}
```

Reason: this makes the fuzzy capability observable without pretending there is one perfect prose answer. It separates:

- broad scene understanding (`scene_summary`),
- coverage/detail (`objects_and_entities`, `salient_regions`),
- spatial reasoning (`relationships`, locations),
- OCR-ish detail (`text_observed`),
- epistemic honesty (`uncertainties`, `hallucination_risk`).

## Scoring dimensions

Create `vision-description-quality` scorer. It should emit a machine-readable detail packet, not just pass/fail.

Recommended dimensions:

| Dimension | Meaning |
|---|---|
| `coverage_score` | Did it mention enough gold objects/regions? |
| `specificity_score` | Are descriptions concrete rather than generic? |
| `spatial_score` | Does it locate objects/regions reasonably? |
| `relationship_score` | Does it describe overlaps, containment, adjacency, hierarchy? |
| `text_score` | Does it capture visible text where present? |
| `hallucination_score` | Does it avoid forbidden/nonexistent claims? |
| `uncertainty_score` | Does it mark ambiguous/occluded details as uncertain? |
| `vagueness_penalty` | Penalize short generic answers like “a busy image with many objects.” |
| `deception_penalty` | Penalize confident but wrong specifics more than cautious omissions. |
| `utility_score` | Would this help an agent decide where to zoom/click/inspect next? |

Initial weighted score:

```text
coverage             30%
specificity          15%
spatial/regions      15%
relationships        10%
text observed        10%
hallucination/forbid 10%
uncertainty honesty   5%
utility/actionability 5%
```

For early calibration, report all components; do not overfit to one total score.

## Gold data format

Each image fixture should have a manifest JSON:

```json
{
  "image_path": "fixtures/vision/chaotic/desk-clutter-01.png",
  "description_goal": "Describe the chaotic desk scene with enough detail for an agent to know what to inspect next.",
  "required_mentions": [
    {"id": "red_mug", "aliases": ["red mug", "cup"], "region": "lower right", "importance": 3},
    {"id": "yellow_sticky_note", "aliases": ["yellow sticky note", "post-it"], "region": "upper center", "importance": 2}
  ],
  "optional_mentions": [...],
  "forbidden_claims": ["person", "dog", "error banner"],
  "region_expectations": {
    "upper_left": ["calendar", "blue marker"],
    "center": ["open notebook", "tangled cable"]
  },
  "relationship_expectations": [
    {"subject": "red_mug", "relation": "partly behind", "object": "notebook"},
    {"subject": "usb_cable", "relation": "crosses", "object": "keyboard"}
  ],
  "visible_text": [
    {"text": "TODO", "strict": false},
    {"text": "ERR-42", "strict": true}
  ],
  "ambiguous_items": ["small dark object near the upper-right edge"]
}
```

## Fixture image strategy

Use a mixture of generated deterministic images and curated/generated realistic images.

### Tier 1 — deterministic synthetic chaos

Programmatically generate PNG/SVG collages with known manifests. These are ideal for deterministic scoring.

Scenarios:

1. **chaotic-desk-synthetic**
   - 20–35 objects: mug, notebook, keyboard, cable, sticky notes, pen, keys, phone, receipt, coin, small toy.
   - Intent: dense object inventory + spatial coverage.

2. **busy-dashboard-synthetic**
   - Dense UI screenshot: sidebar, cards, two charts, overlapping modal, toast, table rows, small warning icons.
   - Intent: UI comprehension in noisy screens.

3. **warehouse-shelf-synthetic**
   - Shelves/bins/labels/barcodes, partial occlusion, similar-looking boxes.
   - Intent: list-like object recognition plus spatial grouping.

4. **map-board-synthetic**
   - Diagram/board with arrows, colored pins, labels, lines crossing.
   - Intent: relationships and topology.

Advantages:
- cheap to generate,
- gold manifest is exact,
- no licensing risk,
- can make variants with controlled clutter/occlusion levels.

### Tier 2 — realistic/generated chaos

Use image generation or manually curated permissive images, then manually author manifests.

Scenarios:

5. **messy-room-realistic**
   - Cluttered room/workbench.
   - Intent: real-world robustness and ambiguity honesty.

6. **crowded-market-realistic**
   - Many people/signs/stalls/occlusions.
   - Intent: broad scene description, avoid inventing identities/actions.

7. **robot-camera-chaos**
   - Blurry/tilted/partial view, multiple objects, poor lighting.
   - Intent: useful-but-cautious description under degraded conditions.

### Tier 3 — adversarial/negative controls

8. **chaos-with-red-herring-prompt**
   - Prompt asks “is there a fire extinguisher?” when none exists, but scene is cluttered.
   - Tests hallucination restraint under search pressure.

9. **near-miss-similar-objects**
   - e.g. red cup vs red can vs red fire extinguisher-like cylinder.
   - Tests cautious categorization.

10. **text-fragment-trap**
   - Many text snippets; only some are legible.
   - Tests not fabricating full text from partial glyphs.

## Scenario prompts

### General description prompt

```text
Describe this image in enough detail that another agent, who cannot see it, could decide what regions or objects to inspect next. Be concrete about what is visible, where it is, and any important relationships or overlaps. If the image is chaotic or ambiguous, still make a serious attempt, but mark uncertain details as uncertain rather than inventing specifics.
```

### Targeted chaotic description prompt

```text
This is a deliberately cluttered image. Produce a structured description with: overall scene, salient regions, visible objects/entities, spatial relationships, visible text, and uncertainties. Avoid vague summaries like “many objects are present”; name concrete visible items and locations when possible.
```

### Negative control prompt

```text
Look carefully for a fire extinguisher, warning sign, person, or animal. If none is visible, say so explicitly. Do not infer one from vague shapes.
```

## Proposed scenario set for v1

| ID | Fixture | Purpose | Primary score emphasis |
|---|---|---|---|
| `vision.describe-chaotic-desk` | synthetic desk collage | dense object description | coverage, spatial, specificity |
| `vision.describe-busy-dashboard` | synthetic UI dashboard | UI chaos | UI elements, text, overlap, actionability |
| `vision.describe-warehouse-shelf` | synthetic shelves/bins | list/group recognition | inventory, regions, label text |
| `vision.describe-map-board` | diagram/board | relationship/topology | relationships, arrows, labels |
| `vision.describe-messy-room` | realistic clutter | real-world robustness | coverage, uncertainty |
| `vision.describe-degraded-camera` | blurry/tilted clutter | ambiguity honesty | uncertainty, useful partial description |
| `vision.no-fire-extinguisher-red-herring` | clutter negative control | avoid prompted hallucination | forbidden claims, uncertainty |
| `vision.text-fragment-trap` | cluttered labels | avoid fake OCR | text observed, hallucination |

Start with 4 synthetic fixtures first for harness calibration; add realistic fixtures once the scorer is stable.

## Runner changes

Two options:

### Minimal path

Use existing `vision-openai` runner and force the richer schema via `candidate.system_prompt` or a new candidate entry.

Downside: schema is candidate-level, not scenario-level, which is awkward for mixing old UI and new description scenarios.

### Better path

Teach `VisionCandidateRunner` to accept scenario-level schema/system prompt fields:

```json
"input": {
  "prompt": "...",
  "image_paths": ["fixtures/vision/chaotic/desk-clutter-01.png"],
  "response_schema": "vision_description_v1",
  "system_prompt": "You are a careful visual description assistant..."
}
```

If `input.system_prompt` exists, use it instead of the default UI-analysis schema. This keeps old scenarios unchanged and lets description scenarios ask for a better JSON contract.

## Scorer changes

Add `scripts/gb/scorers/vision_description_quality.py`.

Inputs:
- candidate JSON output,
- scenario scoring params:
  - `manifest_path`, or inline `gold_manifest`,
  - `min_required_coverage`,
  - `forbidden_claims`,
  - `min_specificity`,
  - `max_vagueness_ratio`,
  - `strict_text_items`.

Implementation sketch:

1. Parse candidate output from `parsed_response` or raw JSON.
2. Flatten all text fields into normalized text.
3. For each required/optional manifest item, match aliases fuzzily.
4. Check region/location words near matched object mentions if possible.
5. Check relationship phrases by subject/object alias + relation synonym.
6. Check visible text snippets.
7. Scan forbidden claims.
8. Compute vagueness indicators:
   - answer too short,
   - high generic-word ratio (`many`, `various`, `several things`, `items`, `stuff`) without concrete nouns,
   - few object/entity entries.
9. Compute uncertainty honesty:
   - ambiguous manifest items may be omitted or marked uncertain;
   - penalize confident hard claims about ambiguous items.

Output detail:

```json
{
  "coverage": {"required_hit": 18, "required_total": 25, "weighted": 0.72},
  "spatial": {...},
  "relationships": {...},
  "text": {...},
  "forbidden_claims_found": [],
  "vagueness_flags": [],
  "uncertainty_flags": [],
  "failure_category": "vague_summary|hallucinated_absent_object|missed_salient_regions|poor_spatial_detail|null"
}
```

## Calibration reporting

Flat table first:

| Model | Scenario | Pass | Coverage | Specificity | Spatial | Relationships | Text | Hallucination | Vagueness | Tokens | Latency |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

Aggregate by scenario class:

| Model | Dense object | UI chaos | Diagram | Degraded | Negative controls | Avg cost | Notes |
|---|---:|---:|---:|---:|---:|---:|---|

Do not collapse to a single leaderboard too early; the likely useful split is cheap model A is good at UI screenshots, cheap model B is better at real-world clutter, etc.

## Model/cost note

The intended matrix will use a different candidate set than the coding-agent runs: vision-capable, cheaper multimodal models. The standalone research task can identify candidates. GoblinBench should be ready to accept OpenAI-compatible `vision-openai` candidates with model/provider/base_url/max_tokens config.

The scenario suite should preserve token/latency/cost columns and raw responses so model behavior can be inspected qualitatively.

## Recommended implementation order

1. Add scenario-level `input.system_prompt` support to `VisionCandidateRunner`.
2. Add `vision-description-quality` scorer with synthetic-manifest support.
3. Create deterministic synthetic image generator under `scripts/vision-fixtures/`.
4. Generate 4 initial synthetic chaotic fixtures + manifests.
5. Add 4 scenario JSON files using the new scorer.
6. Run deterministic/scripted candidate smoke if available; otherwise run one known vision model as calibration.
7. Add realistic/degraded fixtures after the scorer proves useful.

## Important product interpretation

This benchmark should not reward exhaustive perfect captioning only. A useful cheap vision model should:

- make a sincere attempt at dense description,
- name concrete salient items,
- cover multiple image regions,
- admit uncertainty for occluded/ambiguous details,
- avoid confidently inventing absent objects,
- produce output that helps a downstream agent decide what to inspect next.

That is distinct from pure object-list recall and likely more aligned with Den/agent use cases.
