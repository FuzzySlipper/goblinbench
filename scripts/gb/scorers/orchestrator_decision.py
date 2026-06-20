"""Orchestrator decision scorer — port of OrchestratorDecisionScorer.cs.

Validates orchestrator decision output: next_action, reason, confidence,
forbidden_actions_avoided, required_evidence. Weights: action 50%, confidence
in [0,1] 20%, reason present 15%, arrays present 15%. Default threshold 0.8.
"""

from __future__ import annotations

import json
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


class OrchestratorDecisionScorer:
    id = "orchestrator-decision"
    name = "Orchestrator Decision Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        params = scenario.scoring.params(self.id) if scenario.scoring else {}
        expected_action = _str_param(params, "expected_action")
        forbidden = _str_list_param(params, "forbidden_actions")

        obj = _extract_json_object(candidate_result)
        if obj is None:
            return ScoreResult(
                scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
                success=False, score=0.0, passed=False,
                error="Could not extract a JSON object from candidate output.",
                human_summary="FAIL: orchestrator-decision: no parseable JSON object in output",
                detail={"expected_action": expected_action},
            )

        next_action = _str_field(obj, "next_action")
        reason = _str_field(obj, "reason")
        confidence = _num_field(obj, "confidence")
        has_forbidden_arr = isinstance(obj.get("forbidden_actions_avoided"), list)
        has_evidence_arr = isinstance(obj.get("required_evidence"), list)

        # Hard fail: explicitly forbidden action chosen.
        if next_action and next_action.lower() in [f.lower() for f in forbidden]:
            return ScoreResult(
                scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
                success=True, score=0.0, passed=False,
                human_summary=f"FAIL: orchestrator chose forbidden action '{next_action}'",
                explanation=f"Action '{next_action}' is in the forbidden_actions list for this scenario.",
                detail=_detail(next_action, expected_action, confidence, reason,
                               has_forbidden_arr, has_evidence_arr, forbidden_violated=True),
            )

        action_match = expected_action is None or next_action.lower() == expected_action.lower()
        confidence_ok = confidence is not None and 0.0 <= confidence <= 1.0
        reason_ok = bool(reason and reason.strip())
        structure_ok = has_forbidden_arr and has_evidence_arr

        score = (
            0.50 * (1.0 if action_match else 0.0)
            + 0.20 * (1.0 if confidence_ok else 0.0)
            + 0.15 * (1.0 if reason_ok else 0.0)
            + 0.15 * (1.0 if structure_ok else 0.0)
        )
        threshold = scenario.scoring.threshold(self.id, 0.8) if scenario.scoring else 0.8
        passed = score >= threshold

        if passed:
            summary = (
                f"PASS: action='{next_action}' matched '{expected_action}' ({score:.2f})"
                if expected_action is not None
                else f"PASS: action='{next_action}' valid ({score:.2f})"
            )
        elif expected_action is not None and not action_match:
            summary = f"FAIL: action='{next_action}' expected='{expected_action}' ({score:.2f})"
        else:
            summary = f"FAIL: structural issues in orchestrator output ({score:.2f})"

        return ScoreResult(
            scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
            success=True, score=score, passed=passed, human_summary=summary,
            explanation=_explanation(next_action, expected_action, action_match,
                                      confidence_ok, reason_ok, structure_ok, confidence),
            detail=_detail(next_action, expected_action, confidence, reason,
                           has_forbidden_arr, has_evidence_arr, forbidden_violated=False),
        )


def _extract_json_object(result: CandidateResult) -> dict[str, Any] | None:
    src = result.parsed_response if isinstance(result.parsed_response, dict) else result.output
    if isinstance(src, dict):
        return src
    # Fall back to extracting a JSON object from raw text (models wrap JSON in prose).
    raw = result.raw_response
    if isinstance(raw, str) and raw.strip():
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                v = json.loads(raw[start:end + 1])
                if isinstance(v, dict):
                    return v
            except (ValueError, TypeError):
                pass
    return None


def _str_field(obj: dict[str, Any], key: str) -> str:
    v = obj.get(key)
    return v if isinstance(v, str) else ""


def _num_field(obj: dict[str, Any], key: str) -> float | None:
    v = obj.get(key)
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _str_param(params: dict[str, Any], key: str) -> str | None:
    v = params.get(key)
    return v if isinstance(v, str) else (str(v) if v is not None else None)


def _str_list_param(params: dict[str, Any], key: str) -> list[str]:
    v = params.get(key)
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, str)]


def _explanation(next_action, expected_action, action_match, confidence_ok, reason_ok,
                 structure_ok, confidence) -> str:
    issues: list[str] = []
    if expected_action is not None and not action_match:
        issues.append(f"action '{next_action}' != expected '{expected_action}'")
    if not confidence_ok:
        issues.append(
            f"confidence {confidence:.2f} out of range [0,1]"
            if confidence is not None
            else "confidence field missing or non-numeric"
        )
    if not reason_ok:
        issues.append("reason field missing or empty")
    if not structure_ok:
        issues.append("forbidden_actions_avoided or required_evidence arrays missing")
    return "; ".join(issues) if issues else "All checks passed."


def _detail(next_action, expected_action, confidence, reason, has_forbidden_arr,
            has_evidence_arr, forbidden_violated) -> dict[str, Any]:
    return {
        "next_action": next_action,
        "expected_action": expected_action,
        "action_match": expected_action is None or next_action.lower() == expected_action.lower(),
        "confidence": confidence,
        "reason_present": bool(reason and reason.strip()),
        "forbidden_actions_avoided_present": has_forbidden_arr,
        "required_evidence_present": has_evidence_arr,
        "forbidden_violated": forbidden_violated,
    }
