"""Vision correctness scorer — port of VisionCorrectnessScorer.cs.

Validates Den-Vision-Analyzer-schema output: answer text, elements found,
hallucination risk, and field structure. Weights: answer 40%, hallucination 30%,
elements 20%, structure 10%. Default threshold 0.8.

Params: expected_answer_contains, expected_elements[], forbidden_elements[],
max_hallucination_risk ("low"|"medium"|"high", default "high"), min_confidence.
"""

from __future__ import annotations

import json
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


class VisionCorrectnessScorer:
    id = "vision-correctness"
    name = "Vision Correctness Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        params = scenario.scoring.params(self.id) if scenario.scoring else {}
        expected_answer = _str_param(params, "expected_answer_contains")
        expected_elements = _str_list_param(params, "expected_elements")
        forbidden_elements = _str_list_param(params, "forbidden_elements")
        max_risk = _str_param(params, "max_hallucination_risk") or "high"
        min_confidence = _num_param(params, "min_confidence") or 0.0

        obj = _extract_json_object(candidate_result)
        if obj is None:
            return ScoreResult(
                scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
                success=False, score=0.0, passed=False,
                error="Could not extract a JSON object from candidate output.",
                human_summary="FAIL: vision-correctness: no parseable JSON object in output",
            )

        answer = _str_field(obj, "answer")
        hallucination_risk = _str_field(obj, "hallucination_risk")
        confidence = _num_field(obj, "confidence")
        actionability = _num_field(obj, "actionability")
        elements_found = _str_array_field(obj, "elements_found")

        # Hard fail: forbidden element claimed as found (hallucination).
        hallucinated = next(
            (fe for fe in forbidden_elements
             if any(fe.lower() in ef.lower() for ef in elements_found)),
            None,
        )
        if hallucinated is not None:
            return ScoreResult(
                scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
                success=True, score=0.0, passed=False,
                human_summary=f"FAIL: vision hallucination — model claimed to see '{hallucinated}' which is absent",
                explanation=f"Element '{hallucinated}' appears in elements_found but is in the forbidden list.",
                detail=_detail(answer, hallucination_risk, confidence, actionability, elements_found, hallucinated),
            )

        answer_ok = bool(answer.strip()) and (
            expected_answer is None or expected_answer.lower() in answer.lower()
        )
        risk_level = _RISK_ORDER.get(hallucination_risk.lower() if hallucination_risk else "", 2)
        max_risk_level = _RISK_ORDER.get(max_risk.lower(), 2)
        hallucination_ok = risk_level <= max_risk_level
        missing_expected = [
            ee for ee in expected_elements
            if not any(ee.lower() in ef.lower() for ef in elements_found)
        ]
        elements_ok = len(missing_expected) == 0
        structure_ok = (
            bool(answer.strip())
            and bool(hallucination_risk)
            and confidence is not None
            and "elements_found" in obj
        )

        score = (
            0.40 * (1.0 if answer_ok else 0.0)
            + 0.30 * (1.0 if hallucination_ok else 0.0)
            + 0.20 * (1.0 if elements_ok else 0.0)
            + 0.10 * (1.0 if structure_ok else 0.0)
        )
        threshold = scenario.scoring.threshold(self.id, 0.8) if scenario.scoring else 0.8
        passed = score >= threshold

        if passed:
            tail = f", answer contains '{expected_answer}'" if expected_answer is not None else ""
            summary = f"PASS: vision analysis valid ({score:.2f}){tail}"
        else:
            summary = _fail_summary(answer_ok, hallucination_ok, elements_ok, structure_ok,
                                     expected_answer, missing_expected, hallucination_risk, max_risk, score)

        return ScoreResult(
            scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
            success=True, score=score, passed=passed, human_summary=summary,
            explanation=_explanation(answer_ok, hallucination_ok, elements_ok, structure_ok,
                                      expected_answer, missing_expected, hallucination_risk,
                                      max_risk, confidence, min_confidence),
            detail=_detail(answer, hallucination_risk, confidence, actionability, elements_found, None),
        )


def _extract_json_object(result: CandidateResult) -> dict[str, Any] | None:
    src = result.parsed_response if isinstance(result.parsed_response, dict) else result.output
    if isinstance(src, dict):
        return src
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


def _str_array_field(obj: dict[str, Any], key: str) -> list[str]:
    v = obj.get(key)
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, str)]


def _str_param(params: dict[str, Any], key: str) -> str | None:
    v = params.get(key)
    return v if isinstance(v, str) else (str(v) if v is not None else None)


def _num_param(params: dict[str, Any], key: str) -> float | None:
    v = params.get(key)
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _str_list_param(params: dict[str, Any], key: str) -> list[str]:
    v = params.get(key)
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, str)]


def _fail_summary(answer_ok, hallucination_ok, elements_ok, structure_ok, expected_answer,
                  missing, risk_level, max_risk, score) -> str:
    if not answer_ok and expected_answer is not None:
        return f"FAIL: answer does not contain '{expected_answer}' ({score:.2f})"
    if not hallucination_ok:
        return f"FAIL: hallucination_risk='{risk_level}' exceeds max='{max_risk}' ({score:.2f})"
    if not elements_ok:
        return f"FAIL: expected elements not found: {', '.join(missing)} ({score:.2f})"
    return f"FAIL: structural issues in vision output ({score:.2f})"


def _explanation(answer_ok, hallucination_ok, elements_ok, structure_ok, expected_answer,
                 missing, risk_level, max_risk, confidence, min_confidence) -> str:
    issues: list[str] = []
    if not answer_ok:
        issues.append(
            f"answer does not contain '{expected_answer}'"
            if expected_answer is not None
            else "answer field missing or empty"
        )
    if not hallucination_ok:
        issues.append(f"hallucination_risk '{risk_level}' exceeds allowed max '{max_risk}'")
    if not elements_ok:
        issues.append(f"expected elements missing from elements_found: {', '.join(missing)}")
    if not structure_ok:
        issues.append("required output fields missing")
    if confidence is not None and confidence < min_confidence:
        issues.append(f"confidence {confidence:.2f} < min {min_confidence:.2f}")
    return "; ".join(issues) if issues else "All checks passed."


def _detail(answer, hallucination_risk, confidence, actionability, elements_found, hallucinated) -> dict[str, Any]:
    return {
        "answer_preview": (answer[:120] + "...") if len(answer) > 120 else answer,
        "hallucination_risk": hallucination_risk or None,
        "confidence": confidence,
        "actionability": actionability,
        "elements_found_count": len(elements_found),
        "elements_found": elements_found,
        "hallucinated_element": hallucinated,
    }
