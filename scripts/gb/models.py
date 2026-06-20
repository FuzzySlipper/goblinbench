"""Domain models — Python port of GoblinBench.Core.

These dataclasses mirror the C# records/classes one-for-one. Each exposes a
``json_dict()`` method that returns an ordered dict with the exact snake_case
keys produced by the C# ``[JsonPropertyName]`` attributes, so serialized
artifacts match the .NET contract field-for-field.

Field ordering matters: gb-results/gb-score parse semantically so order is not
required, but matching the .NET declaration order keeps diffs readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CandidateKind(Enum):
    """PascalCase values match the C# JsonStringEnumConverter output exactly."""

    Unknown = "Unknown"
    OpenAiModel = "OpenAiModel"
    HermesProfile = "HermesProfile"
    ServiceEndpoint = "ServiceEndpoint"
    ExternalCli = "ExternalCli"
    LocalModel = "LocalModel"
    CodingAgent = "CodingAgent"

    @classmethod
    def parse(cls, raw: Any) -> "CandidateKind":
        """Parse from a candidates.json ``kind`` value (string or enum-ish)."""
        if raw is None:
            return cls.Unknown
        if isinstance(raw, cls):
            return raw
        s = str(raw).strip()
        # Case-insensitive lookup against enum names (C# is case-insensitive on
        # enum deserialization via JsonStringEnumConverter + PropertyNameCaseInsensitive).
        for member in cls:
            if member.value.lower() == s.lower():
                return member
        return cls.Unknown


# --------------------------------------------------------------------------- #
# Scenario graph (loaded from suites/<suite>/*.json)
# --------------------------------------------------------------------------- #

@dataclass
class JudgeConfig:
    model: str | None = None
    provider: str | None = None
    prompt_version: str = "v1"
    temperature: float = 0.0
    max_tokens: int = 1024


@dataclass
class ScoringConfig:
    scorers: list[str] = field(default_factory=list)
    parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    judges: dict[str, JudgeConfig] = field(default_factory=dict)

    def threshold(self, scorer_id: str, default_value: float) -> float:
        return self.thresholds.get(scorer_id, default_value)

    def params(self, scorer_id: str) -> dict[str, Any]:
        return self.parameters.get(scorer_id, {})


@dataclass
class FixtureConfig:
    setup_commands: list[str] = field(default_factory=list)
    teardown_commands: list[str] = field(default_factory=list)
    provision_files: dict[str, str] = field(default_factory=dict)


@dataclass
class Scenario:
    id: str = ""
    version: str = "1.0.0"
    name: str = ""
    description: str = ""
    suite: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    fixture: FixtureConfig | None = None
    scoring: ScoringConfig | None = None
    timeout_seconds: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Scenario":
        scoring_raw = raw.get("scoring")
        scoring = None
        if scoring_raw:
            judges_raw = scoring_raw.get("judges") or {}
            scoring = ScoringConfig(
                scorers=list(scoring_raw.get("scorers") or []),
                parameters=dict(scoring_raw.get("parameters") or {}),
                thresholds={k: float(v) for k, v in (scoring_raw.get("thresholds") or {}).items()},
                judges={k: JudgeConfig(**v) for k, v in judges_raw.items()},
            )
        fixture_raw = raw.get("fixture")
        fixture = (
            FixtureConfig(
                setup_commands=list(fixture_raw.get("setup_commands") or []),
                teardown_commands=list(fixture_raw.get("teardown_commands") or []),
                provision_files=dict(fixture_raw.get("provision_files") or {}),
            )
            if fixture_raw
            else None
        )
        return cls(
            id=raw.get("id") or "",
            version=raw.get("version") or "1.0.0",
            name=raw.get("name") or "",
            description=raw.get("description") or "",
            suite=raw.get("suite") or "",
            input=dict(raw.get("input") or {}),
            fixture=fixture,
            scoring=scoring,
            timeout_seconds=int(raw.get("timeout_seconds") or 0),
        )


# --------------------------------------------------------------------------- #
# Candidate config (loaded from candidates.json — never written to artifacts)
# --------------------------------------------------------------------------- #

@dataclass
class CandidateConfig:
    id: str = ""
    name: str = ""
    kind: CandidateKind = CandidateKind.Unknown
    model: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    base_url: str | None = None
    profile: str | None = None
    cli_command: str | None = None
    cli_args: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    runtime_metadata: dict[str, str] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    # NOTE: api_key_env / api_key are [JsonIgnore] in C# and runtime-only.
    # We keep them here for future OpenAiChat/CodingAgent runners; they are
    # populated from env vars at run time and never serialized.
    api_key_env: str | None = None
    api_key: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CandidateConfig":
        return cls(
            id=raw.get("id") or "",
            name=raw.get("name") or "",
            kind=CandidateKind.parse(raw.get("kind")),
            model=raw.get("model"),
            provider=raw.get("provider"),
            endpoint=raw.get("endpoint"),
            base_url=raw.get("base_url"),
            profile=raw.get("profile"),
            cli_command=raw.get("cli_command"),
            cli_args=list(raw.get("cli_args") or []),
            system_prompt=raw.get("system_prompt"),
            runtime_metadata={k: str(v) for k, v in (raw.get("runtime_metadata") or {}).items()},
            config=dict(raw.get("config") or {}),
            api_key_env=raw.get("api_key_env"),
        )


# --------------------------------------------------------------------------- #
# Result graph (written to run.json + per-candidate artifacts)
# --------------------------------------------------------------------------- #

@dataclass
class ModelIdentity:
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None
    display_name: str | None = None

    def json_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "base_url": self.base_url,
            "display_name": self.display_name,
        }


@dataclass
class TraceEvent:
    timestamp: str
    event: str
    data: Any = None

    def json_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "event": self.event, "data": self.data}


@dataclass
class ScoreResult:
    scorer_id: str = ""
    scorer_name: str = ""
    scoring_kind: str = "deterministic"
    success: bool = False
    error: str | None = None
    score: float | None = None
    passed: bool | None = None
    explanation: str | None = None
    human_summary: str | None = None
    judge_model: str | None = None
    judge_prompt_version: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def json_dict(self) -> dict[str, Any]:
        return {
            "scorer_id": self.scorer_id,
            "scorer_name": self.scorer_name,
            "scoring_kind": self.scoring_kind,
            "success": self.success,
            "error": self.error,
            "score": self.score,
            "passed": self.passed,
            "explanation": self.explanation,
            "human_summary": self.human_summary,
            "judge_model": self.judge_model,
            "judge_prompt_version": self.judge_prompt_version,
            "detail": self.detail,
        }


@dataclass
class CandidateResult:
    candidate_id: str = ""
    candidate_name: str = ""
    candidate_kind: CandidateKind = CandidateKind.Unknown
    model_identity: ModelIdentity | None = None
    success: bool = False
    error: str | None = None
    duration_ms: int = 0
    raw_response: str | None = None
    parsed_response: Any = None
    output: Any = None
    trace: list[TraceEvent] = field(default_factory=list)
    scores: list[ScoreResult] = field(default_factory=list)
    artifact_directory: str | None = None

    def json_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "candidate_kind": self.candidate_kind,  # Enum → PascalCase via serialize
            "model_identity": self.model_identity,
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "raw_response": self.raw_response,
            "parsed_response": self.parsed_response,
            "output": self.output,
            "trace": self.trace,
            "scores": self.scores,
            "artifact_directory": self.artifact_directory,
        }


@dataclass
class PerScenarioResult:
    scenario_id: str = ""
    scenario_version: str = ""
    candidate_results: list[CandidateResult] = field(default_factory=list)

    def json_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "candidate_results": self.candidate_results,
        }


@dataclass
class RunResult:
    run_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    label: str | None = None
    scenarios: list[str] = field(default_factory=list)
    results: list[PerScenarioResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def json_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "label": self.label,
            "scenarios": self.scenarios,
            "results": self.results,
            "metadata": self.metadata,
        }
