# Vision Suite Guide

GoblinBench Vision UI Analysis evaluates models and services for use behind the Den Vision Analyzer capability. This guide explains the expected output schema, how to call the vision service, and when to use synchronous analysis versus an async VisionReviewer profile.

## Output schema

All vision candidates must return a JSON object with these fields:

```json
{
  "elements_found": ["error_banner", "modal_dialog"],
  "answer": "direct answer to the question asked",
  "confidence": 0.92,
  "hallucination_risk": "low|medium|high",
  "suggested_action": "next action, or null",
  "actionability": 0.8
}
```

| Field | Type | Description |
|---|---|---|
| `elements_found` | string[] | UI elements the model can actually see. Never fabricate. |
| `answer` | string | Direct, specific answer to the scenario question. |
| `confidence` | float [0,1] | Model's self-assessed confidence in the analysis. |
| `hallucination_risk` | string | Self-assessed risk of confabulation: `"low"`, `"medium"`, or `"high"`. |
| `suggested_action` | string\|null | Most likely next user interaction, or null if not applicable. |
| `actionability` | float [0,1] | How actionable the analysis is for the caller. |

## Calling the vision service synchronously

Use synchronous invocation when:
- The result is needed immediately to continue a workflow (e.g., an agent must decide its next action based on the screenshot)
- The scenario is simple: single screenshot, binary answer (error present / absent)
- Latency matters: the caller is blocking on the result
- The task is part of a tight retry loop where speed matters more than depth

```csharp
// Synchronous example: agent checks for error banner before proceeding
var result = await visionService.AnalyzeAsync(screenshot, "Is an error banner visible?");
if (result.Answer.Contains("yes", StringComparison.OrdinalIgnoreCase))
    await HandleErrorStateAsync();
```

A `VisionCandidateRunner` with an OpenAI-compatible vision model is the recommended path for synchronous analysis. Configure `cli_command = "vision-openai"` in your `candidates.json` entry.

## Using an async VisionReviewer profile

Use an async VisionReviewer when:
- Analysis depth matters more than latency (e.g., architectural review, accessibility audit)
- Multiple screenshots need to be compared in sequence
- The analysis feeds into a document or report rather than a real-time decision
- You want a second opinion on a borderline vision result from a faster model
- The scenario involves subtle judgment: distinguishing a loading spinner from an error state, reading small text, or interpreting partially-rendered UI

A VisionReviewer is a Hermes profile (`HermesProfileRunner`) configured with a vision-capable model and a reviewer system prompt. It runs asynchronously, picks up work via Den task assignment, and posts its analysis as a task completion artifact.

```json
// candidates.json example: async reviewer
{
  "id": "hermes-vision-reviewer",
  "name": "Hermes Vision Reviewer",
  "kind": "HermesProfile",
  "profile": "vision-reviewer-v1",
  "runtime_metadata": {
    "role": "vision_reviewer",
    "depth": "deep"
  }
}
```

## When to escalate to VisionReviewer vs accept synchronous result

| Condition | Recommendation |
|---|---|
| `confidence >= 0.9` and `hallucination_risk = "low"` | Accept synchronous result |
| `confidence < 0.7` | Escalate to VisionReviewer |
| `hallucination_risk = "high"` | Escalate to VisionReviewer |
| Multiple screenshots, cross-frame reasoning required | Use VisionReviewer |
| Agent is mid-workflow and needs an immediate next-step | Synchronous |
| Result feeds a report, ADR, or long-running review | Async VisionReviewer |

## Fixture images

Fixture images live in `fixtures/vision/`. The current fixtures are minimal synthetic PNGs for smoke-testing the harness pipeline without a live vision model. Replace them with real application screenshots before running production benchmarks.

| File | Represents |
|---|---|
| `error-banner.png` | App UI with a red error banner at the top |
| `modal-dialog.png` | App UI with a centered modal dialog on a dimmed background |
| `disabled-controls.png` | Form with enabled controls (left) and disabled/grayed controls (right) |
| `expected-ui.png` | Clean expected UI state (for comparison scenarios) |
| `absent-element.png` | Clean, featureless UI with no error or alert elements (hallucination test) |
| `action-suggestion.png` | App with a prominent blue call-to-action header |

## Scoring

Vision scenarios use three scorers:

- **`vision-correctness`**: checks answer content, elements found, hallucination risk, and structural validity
- **`vision-description-quality`**: scores chaotic / dense image descriptions against a manifest of salient objects, regions, text, relationships, forbidden claims, and ambiguity expectations
- **`schema-compliance`**: validates the output object shape against the expected schema
- **`latency`**: records execution time for model/service comparison

Both `vision-correctness` and `schema-compliance` require a score of ≥ 0.8 to pass. The hallucination scenario (`absent-element-hallucination`) additionally enforces `max_hallucination_risk: "low"` and `forbidden_elements` to hard-fail any model that fabricates absent UI elements.

## Visual-inspect / chaotic description scenarios

Task #3425 adds `visual-inspect` benchmark coverage for selecting cheap but useful vision models before screenshot checks become hard review gates. The service contract comes from `den-services/visual-inspect-service-design-3317`: screenshots plus criteria in; structured `pass|fail|uncertain`, confidence, observations, evidence regions, follow-up hints, and warnings out. The GoblinBench suite can run direct OpenAI-compatible vision candidates first; it does not require the full `visual-inspect` service to exist.

Chaotic-description scenarios use `input.response_schema = "vision_description_v1"`, which makes the `vision-openai` runner use a richer scenario-level JSON prompt containing:

```json
{
  "scene_summary": "...",
  "salient_regions": [{"region": "center", "description": "..."}],
  "objects_and_entities": [{"label": "...", "location": "...", "attributes": ["..."]}],
  "relationships": ["..."],
  "text_observed": ["..."],
  "uncertainties": ["..."],
  "answer": "...",
  "confidence": 0.0,
  "hallucination_risk": "low|medium|high"
}
```

Synthetic chaotic fixtures live in `fixtures/vision/chaotic/` and are generated by:

```bash
python3 scripts/vision-fixtures/generate_chaotic_fixtures.py
```

Initial scenarios:

| Scenario | Purpose |
|---|---|
| `vision.describe-chaotic-desk` | Dense object inventory, spatial coverage, visible text, ambiguity honesty |
| `vision.describe-busy-dashboard` | Noisy UI state with sidebar/cards/chart/table/modal/toast/text |
| `vision.describe-warehouse-shelf` | Shelf/bin labels, inventory grouping, occlusion, uncertainty |
| `vision.describe-map-board` | Diagram topology, node labels, relationships, blocked-route text |

Candidate examples:

```json
{
  "id": "scripted-deterministic",
  "name": "Scripted Deterministic Candidate",
  "kind": "Unknown",
  "cli_command": "scripted"
}
```

Local den-router candidate, no API key required when the router is configured that way:

```json
{
  "id": "den-router-<model>-vision",
  "name": "Den Router <model> Vision",
  "kind": "OpenAiModel",
  "model": "<den-router-model-id>",
  "provider": "den-router",
  "base_url": "http://127.0.0.1:18082/v1",
  "cli_command": "vision-openai",
  "config": {"temperature": 0.0, "max_tokens": 3072}
}
```

Hosted OpenAI-compatible candidate, only when the endpoint requires an API key:

```json
{
  "id": "gpt-4o-vision",
  "name": "GPT-4o Vision",
  "kind": "OpenAiModel",
  "model": "gpt-4o",
  "provider": "openai",
  "cli_command": "vision-openai",
  "api_key_env": "OPENAI_API_KEY",
  "config": {"temperature": 0.2, "max_tokens": 2048}
}
```

Direct Lemonade Server candidate on den-nimo; no den-router or API key required:

```json
{
  "id": "lemonade-qwen35-4b-vision",
  "name": "Lemonade Qwen3.5 4B Vision",
  "kind": "OpenAiModel",
  "model": "Qwen3.5-4B-GGUF",
  "provider": "lemonade",
  "base_url": "http://192.168.1.23:13305/v1",
  "cli_command": "vision-openai",
  "config": {"temperature": 0.0, "max_tokens": 3072}
}
```

Other local OpenAI-compatible endpoint; omit `api_key_env` if the endpoint does not require auth:

```json
{
  "id": "local-qwen-vl-vision",
  "name": "Local Qwen VL Vision",
  "kind": "OpenAiModel",
  "model": "<local-vision-model-id>",
  "provider": "local-openai-compatible",
  "base_url": "http://<host>:<port>/v1",
  "cli_command": "vision-openai",
  "config": {"temperature": 0.0, "max_tokens": 3072}
}
```

Use the scripted candidate for deterministic pipeline checks first:

```bash
python3 scripts/gb-run.py --suite vision --candidate scripted-deterministic
```
