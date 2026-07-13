"""Stable provenance envelope for model-core and environment-realized runs.

The envelope is deliberately JSON-shaped. Runners may contribute exact
substrate/profile/usage fields, while ``finalize_environment`` supplies the
common harness, outcome, and honest cost defaults after scoring completes.
Secrets are removed before requested candidate configuration is retained.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import CandidateConfig, CandidateKind, CandidateResult, Scenario

ENVIRONMENT_SCHEMA_VERSION = "1"
ENVIRONMENT_LANES = frozenset({"model-core", "environment-realized"})
COST_CLASSIFICATIONS = frozenset({
    "metered", "estimated", "opaque-subscription", "unavailable",
})

_SECRET_FRAGMENTS = ("secret", "token", "password", "api_key", "api-key", "authorization")


def finalize_environment(
    candidate: CandidateConfig,
    scenario: Scenario,
    runner_name: str,
    result: CandidateResult,
) -> dict[str, Any]:
    """Return a complete, validated environment envelope for one result."""
    supplied = result.environment if isinstance(result.environment, dict) else {}
    lane = _lane(candidate, supplied)
    configured = candidate.config.get("environment")
    configured = configured if isinstance(configured, dict) else {}

    requested_config = _redact(candidate.config)
    requested_config_hash = _hash_json(requested_config)
    primary = _primary_score(result)
    model_identity = result.model_identity

    base: dict[str, Any] = {
        "schema_version": ENVIRONMENT_SCHEMA_VERSION,
        "lane": lane,
        "name": str(
            supplied.get("name")
            or configured.get("name")
            or (runner_name if lane == "environment-realized" else "direct-model")
        ),
        "model": {
            "requested": candidate.model,
            "resolved": model_identity.model if model_identity else candidate.model,
            "provider_requested": candidate.provider,
            "provider_resolved": model_identity.provider if model_identity else candidate.provider,
            "reasoning_effort": candidate.config.get("reasoning_effort") or candidate.config.get("effort"),
            "requested_config": requested_config,
            "requested_config_sha256": requested_config_hash,
        },
        "substrate": {
            "kind": runner_name,
            "name": runner_name,
            "version": None,
            "transport": None,
        },
        "profile": {
            "id": candidate.profile or candidate.config.get("profile_id"),
            "revision": None,
            "role": candidate.config.get("role"),
            "prompt_assembly_id": candidate.config.get("prompt_assembly_id"),
            "tool_catalog_sha256": candidate.runtime_metadata.get("tool_catalog_sha256"),
        },
        "harness": {
            "runner": runner_name,
            "runner_version": "python-v1",
            "scenario_id": scenario.id,
            "scenario_version": scenario.version,
            "fixture_case": scenario.input.get("fixture_case"),
            "workspace_sha256": None,
        },
        "execution": {
            "runner_status": "completed" if result.success else "failed",
            "substrate_status": "completed" if result.success else "failed",
            "terminal_status": "completed" if result.success else "failed",
            "elapsed_ms": result.duration_ms,
            "retries": 0,
            "tool_calls": None,
            "command_cycles": None,
        },
        "usage": {
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "reasoning_output_tokens": None,
            "total_tokens": None,
            "model_context_window": None,
        },
        "cost": {
            "classification": "unavailable",
            "amount": None,
            "currency": None,
            "basis": None,
        },
        "outcome": {
            "runner_success": result.success,
            "primary_scorer_id": primary.get("scorer_id") if primary else None,
            "score": primary.get("score") if primary else None,
            "passed": primary.get("passed") if primary else None,
            "summary": primary.get("human_summary") if primary else None,
        },
    }
    merged = _deep_merge(base, configured)
    merged = _deep_merge(merged, supplied)
    merged["schema_version"] = ENVIRONMENT_SCHEMA_VERSION
    merged["lane"] = lane
    merged["execution"]["elapsed_ms"] = result.duration_ms
    merged["outcome"] = base["outcome"]
    _validate(merged)
    return merged


def snapshot_sha256(snapshot: dict[str, Any]) -> str:
    """Hash a fixture snapshot without depending on absolute workspace paths."""
    rows = [
        {"path": path, "size": item.size, "sha256": item.sha256}
        for path, item in sorted(snapshot.items())
    ]
    return _hash_json(rows)


def json_sha256(value: Any) -> str:
    return _hash_json(value)


def refresh_environment_outcomes(run_payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Refresh scored outcomes after post-processing and return artifact targets.

    Some scorer plugins run after the initial candidate artifacts are written.
    Keeping this pass JSON-shaped lets the canonical run payload and its
    environment artifacts be updated from the exact post-processor output.
    """
    artifacts: list[tuple[str, dict[str, Any]]] = []
    for scenario_result in run_payload.get("results") or []:
        for result in scenario_result.get("candidate_results") or []:
            environment = result.get("environment")
            if not isinstance(environment, dict):
                continue
            primary = _primary_score_dict(result.get("scores") or [])
            environment["outcome"] = {
                "runner_success": bool(result.get("success")),
                "primary_scorer_id": primary.get("scorer_id") if primary else None,
                "score": primary.get("score") if primary else None,
                "passed": primary.get("passed") if primary else None,
                "summary": primary.get("human_summary") if primary else None,
            }
            artifact_directory = result.get("artifact_directory")
            if isinstance(artifact_directory, str) and artifact_directory:
                artifacts.append((artifact_directory, environment))
    return artifacts


def _lane(candidate: CandidateConfig, supplied: dict[str, Any]) -> str:
    raw = supplied.get("lane") or candidate.config.get("environment_lane")
    if raw is not None:
        value = str(raw)
        if value not in ENVIRONMENT_LANES:
            raise ValueError(f"environment lane must be one of {sorted(ENVIRONMENT_LANES)}")
        return value
    if candidate.kind in {
        CandidateKind.CodingAgent,
        CandidateKind.HermesProfile,
        CandidateKind.ServiceEndpoint,
        CandidateKind.ExternalCli,
    }:
        return "environment-realized"
    return "model-core"


def _primary_score(result: CandidateResult) -> dict[str, Any] | None:
    for score in result.scores:
        if score.passed is not None and score.scorer_id not in {"noop", "latency"}:
            return score.json_dict()
    for score in result.scores:
        if score.scorer_id not in {"noop", "latency"}:
            return score.json_dict()
    return result.scores[0].json_dict() if result.scores else None


def _primary_score_dict(scores: list[Any]) -> dict[str, Any] | None:
    values = [value for value in scores if isinstance(value, dict)]
    for score in values:
        if score.get("passed") is not None and score.get("scorer_id") not in {"noop", "latency"}:
            return score
    for score in values:
        if score.get("scorer_id") not in {"noop", "latency"}:
            return score
    return values[0] if values else None


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _redact(value: Any, key: str = "") -> Any:
    if any(fragment in key.lower() for fragment in _SECRET_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate(envelope: dict[str, Any]) -> None:
    lane = envelope.get("lane")
    if lane not in ENVIRONMENT_LANES:
        raise ValueError(f"environment lane must be one of {sorted(ENVIRONMENT_LANES)}")
    cost = envelope.get("cost")
    if not isinstance(cost, dict) or cost.get("classification") not in COST_CLASSIFICATIONS:
        raise ValueError(
            "cost.classification must be metered, estimated, opaque-subscription, or unavailable"
        )
    if cost.get("classification") in {"opaque-subscription", "unavailable"} and cost.get("amount") is not None:
        raise ValueError("opaque-subscription/unavailable cost must not claim a numeric amount")
