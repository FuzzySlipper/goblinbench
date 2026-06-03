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
- **`schema-compliance`**: validates the output object shape against the expected schema
- **`latency`**: records execution time for model/service comparison

Both `vision-correctness` and `schema-compliance` require a score of ≥ 0.8 to pass. The hallucination scenario (`absent-element-hallucination`) additionally enforces `max_hallucination_risk: "low"` and `forbidden_elements` to hard-fail any model that fabricates absent UI elements.
