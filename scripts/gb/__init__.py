"""GoblinBench runner — Python port of the .NET harness (Milestone 1).

This package replaces the execution layer (src/GoblinBench.Runner + Candidates
+ the deterministic Scorers + Core) with a drop-in Python implementation that
produces the same on-disk artifact tree under ``runs/<run-id>/``.

Scope (Milestone 1):
  - domain models (Scenario, CandidateConfig, RunContext, results)
  - scenario discovery
  - NoOp + Scripted candidate runners (green path)
  - Latency + SchemaCompliance scorers (deterministic)
  - main loop (arg parsing, dispatch, artifact writing, gb-score.py handoff)

Deferred:
  - ReportServer / ReportGenerator (dead — not used anymore)
  - OpenAiChat / CodingAgent / MCP / Vision / Hermes runners (Milestone 2+)
  - heavier scorers (CodingTest, McpToolUse, VisionCorrectness, ...)

Downstream tooling (``scripts/gb-score.py``, ``scripts/gb-results.py``, and the
``scripts/scorers/*.py`` plugin dir) reads artifacts via a stable on-disk
contract and is therefore language-agnostic and untouched by this port.
"""

__all__ = ["models", "context", "discovery", "registry", "serialize"]
