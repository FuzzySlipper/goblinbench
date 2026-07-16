# Codebase analysis benchmark methodology

How to design and run codebase analysis benchmarks (Mode A: fixed packet, Mode B: tool-driven workspace).

## When to use this

Building a benchmark to evaluate models on architectural judgment, codebase review quality, or reviewer/planner suitability. Not for testing coding ability (use the coding suite) or tool-call discipline (use MCP suites) — this tests higher-level codebase comprehension and structured analysis.

## Core design

### Fixture = frozen real codebase + planted issues + decoys

- Start from a real codebase (e.g. `den-core`), not a fully synthetic toy repo. Real architecture gives the benchmark texture and makes architectural judgment meaningful.
- Fork/hack/freeze a specific commit into a private fixture. Do **not** evaluate against a live, evolving repo.
- ~20-40 files, ~2000-5000 lines of code is enough for a v1 fixture.
- Plant 10-14 issues. Each needs category, severity, scope (single_file / cross_file), expected_evidence (file paths + diagnosis patterns), and good_fix_properties.

### Gold ledger design

Each gold issue should have:

```json
{
  "id": "contract-paging-mismatch",
  "category": "api-contract-violation",
  "severity": "high",
  "scope": "cross_file",
  "description": "Short description of the planted issue",
  "planted_in": ["src/Service/Routes/X.cs", "src/Core/Data/Y.cs"],
  "expected_evidence": [
    "X returns nextCursor but consumer Y ignores it",
    "Y uses pageNumber/pageSize instead of cursor"
  ],
  "acceptable_diagnoses": [
    "Cursor and offset pagination mixed",
    "Inconsistent pagination strategy between endpoints"
  ],
  "good_fix_properties": [
    "Unify pagination strategy",
    "OR consumer reads nextCursor from response"
  ]
}
```

### Decoys (must include)

Add 3-5 patterns that look suspicious but are valid:

- Pre-warming cache on startup (not source-of-truth confusion)
- LAN default with documented env override (not hardcoded config drift)
- Compat route kept for backward compatibility (not dead code)
- Deprecated field retained for wire format (not layering violation)

Decoys prevent generic "use best practices" lint essays from scoring well.

### Mode A: fixed repo packet

The fixture is pre-bundled into a single packet with full source code, project brief, architecture doc, API contract, and deployment notes.

**CRITICAL: The packet MUST include actual source file contents inline, not just file descriptions.**

✅ CORRECT: Full source code embedded:
```
## src/DenCore/Data/TaskRepository.cs
```csharp
using System.Collections.Concurrent;
public class TaskRepository {
    private static readonly ConcurrentDictionary<long, ProjectTask> _cache = new();
    ...
}
```
```

❌ WRONG (hint-leakage): Prose descriptions of what each file does:
```
## Data Layer (Repositories)
- src/DenCore/Data/MessageRepository.cs — Offset and cursor pagination methods
- src/DenCore/Data/TaskRepository.cs — In-memory cache with concurrency notes
```

The prose approach leaks the answer key — models can rephrase the description as their finding without analyzing actual code. Only minimax M3 was honest enough to say "I need the actual code."

Target packet size: ~60-100KB (~15-25k tokens). Large-model friendly.

Mode A tests: raw reasoning quality, architecture understanding, prioritization, evidence use within bounded input.

### Mode B: tool-driven workspace access (separate eval)

Same fixture, but the model is given workspace access and can inspect files using tools/CLI.
This tests: file navigation, search strategy, thoroughness, tool discipline, evidence gathering.
Mode B can surface different rankings than Mode A — disciplined tool-callers (StepFun, MiniMax) may punch above their raw reasoning weight.

## Candidate runner design

### Prompt structure

```
You are a senior software architect reviewing a codebase.
...
## Context
{full_packet}

## Instructions
- Read the code and identify issues across all categories
- Prioritize — lead with most impactful
- Be specific — cite exact paths, lines, and quotes
- Consider tradeoffs — some valid patterns look wrong
- Propose concrete fixes
```

### Output format requirement

Request TWO outputs:
1. `analysis.md` — free-form markdown analysis
2. `findings.json` — structured JSON codeblock at the end

Finding schema:
```json
{
  "findings": [{
    "title": "Short title",
    "category": "contract_mismatch",
    "severity": "high",
    "confidence": 0.9,
    "evidence": [{"path": "src/X.cs", "lines": "12-34", "quote": "relevant code"}],
    "diagnosis": "What is wrong",
    "impact": "What could go wrong",
    "fix": "Proposed fix",
    "fix_scope": "cross_file_refactor"
  }]
}
```

### JSON extraction pitfalls

- Models wrap findings in ` ```json ... ``` ` code fences.
- Nested JSON objects inside findings (evidence arrays, nested objects) break naive `\{.*?\}` regex.
- **Use brace-counting extraction** — find the first `{` after the fence, count brace depth to find matching `}`.
- Truncated JSON (model hits max_tokens mid-output) needs partial extraction: scan for complete `{}`-delimited finding objects after the `"findings": [`, stop when no comma follows a complete object.

### Temperature per model

Some models reject non-1.0 temperature (kimi-code, kimi). Use a lookup dict:

```python
MODEL_TEMPS = {
    'kimi-code': 1.0,
    'kimi': 1.0,
}
```

## Scoring: two-layer judge

### Layer 1: gold ledger matching

A judge model maps each candidate finding to the hidden issue ledger:

- `match_gold_id`: which issue it matches (or null)
- `match_quality`: good_match / partial_match / no_match
- `is_false_positive`: flagged something that isn't a problem
- `is_decoy_hit`: flagged a valid decoy pattern
- `is_bonus_finding`: genuine issue NOT in the gold ledger
- `evidence_quality`: good / adequate / poor / missing (does it cite real files/lines/quotes?)
- `severity_agreement`: matches / model_overrates / model_underrates / no_match

### Fallback scoring (judge output truncation)

The judge model may truncate and lose the `scoring` section (judge prompt + response can exceed 16k tokens). When this happens, the report generator falls back to computing scores from the `findings` list in `judge_output`: compute TP, FP, decoy, bonus, evidence quality, and severity calibration from the per-finding annotations. This is handled by the runner script automatically — no manual intervention needed, but be aware that report metrics may come from the findings list rather than a structured scoring block.

### Layer 2: qualitative excerpts

The judge also selects:

- `best_finding`: the most insightful finding with quote
- `key_miss`: the most important gold issue the candidate missed
- `notable_exchange`: for multi-round tests, how the model responded to peer feedback

### Scoring metrics

| Dimension | Meaning |
|---|---|
| gold_recall | Fraction of gold issues matched (weighted by severity optional) |
| true_positive_count / false_positive_count | Precision signal |
| decoy_hit_count | How many decoys were flagged (penalty) |
| bonus_finding_count | Real issues found outside the ledger (bonus) |
| evidence_quality_score | 0-1: does the model cite real code? |
| severity_calibration_score | 0-1: do severity assignments match gold? |
| fix_quality_notes | Qualitative text on fix quality |
| overall_assessment | Text summary from judge |

### Judge prompt size management

The judge prompt includes the full gold ledger + candidate findings. This can exceed 10k tokens. **Set judge max_tokens >= 16384** and truncate ledger descriptions to ~200 chars each to keep prompt manageable.

## Report format

The comparative report should have five sections:

1. **Leaderboard table** — Recall, TP, FP, decoy hits, bonus, evidence quality, severity calibration, duration
2. **Issue coverage matrix** — Gold issue × model, with ✓/~ symbols
3. **Qualitative assessment** — Per-model: best finding excerpt, key miss, overall assessment
4. **Role routing recommendation** — Planner/Architect, Reviewer, Operator, Cheap triage

## Known gotchas

- **Packet hint-leakage is the #1 pitfall.** If the packet describes file purposes ("X has concurrency notes"), models rephrase that as their finding. Always embed raw source code, never issue-hinting prose.
- **Decoys are essential.** Without them, models that shotgun "use best practices" score artificially high.
- **Universal blind spots exist.** The `core-mcp-boundary-leak` (core domain model references MCP-specific concept) was missed by all 8 models in the first run. Some issue categories may need Mode B to surface.
- **Evidence quality varies wildly** — from 0% (generic text) to 100% (exact line/quote citations). This is the most discriminating dimension and maps directly to real review usefulness.
- **judge_candidate uses high max_tokens (16384).** The judge prompt includes gold ledger + candidate findings and can hit 10k+ tokens. Truncated judge output loses the scoring section.
- **`extract_findings` must handle nested braces** — findings contain `evidence[]` with nested JSON objects. Use brace-counting, not greedy/non-greedy regex.
