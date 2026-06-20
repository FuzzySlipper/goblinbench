"""Schema compliance scorer — port of SchemaComplianceScorer.cs.

Validates candidate output against a minimal JSON-Schema subset (``required``
field list + ``properties.<name>.type``). Reports one violation per missing
required field or type mismatch; score = 1.0 when clean, else
max(0.0, 1.0 - 0.2*violations).
"""

from __future__ import annotations

import json
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


# JSON value kind → schema "type" string (mirrors C# GetJsonType).
def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return "unknown"


def _type_matches(actual: str, expected: str) -> bool:
    # Mirrors C# TypeMatches: number/integer are interchangeable; otherwise exact.
    number_like = {"number", "integer"}
    if actual in number_like and expected in number_like:
        return True
    return actual.lower() == expected.lower()


class SchemaComplianceScorer:
    id = "schema-compliance"
    name = "Schema Compliance Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        params = scenario.scoring.params(self.id) if scenario.scoring else {}
        schema = params.get("schema")

        if not isinstance(schema, dict):
            return ScoreResult(
                scorer_id=self.id,
                scorer_name=self.name,
                scoring_kind="deterministic",
                success=False,
                error="No JSON schema configured for schema-compliance scorer.",
                human_summary="FAIL: schema-compliance: no schema configured",
            )

        required_fields = [str(x) for x in (schema.get("required") or [])]
        field_types: dict[str, str] = {}
        for name, prop in (schema.get("properties") or {}).items():
            if isinstance(prop, dict) and "type" in prop:
                field_types[str(name)] = str(prop["type"])

        output = candidate_result.parsed_response
        if output is None:
            output = candidate_result.output
        if output is None:
            return ScoreResult(
                scorer_id=self.id,
                scorer_name=self.name,
                scoring_kind="deterministic",
                success=True,
                score=0.0,
                passed=False,
                explanation="Candidate produced no parseable output.",
                human_summary="FAIL: schema-compliance: no candidate output (0.0)",
            )

        # Normalize to a dict for field access. If the candidate output isn't an
        # object, field checks simply fail (matching C# behavior on a non-object
        # JsonElement where TryGetProperty returns false for everything).
        out_dict: dict[str, Any] = output if isinstance(output, dict) else {}

        violations: list[dict[str, Any]] = []

        for field in required_fields:
            if field not in out_dict:
                violations.append({
                    "path": field,
                    "message": f"Required field '{field}' is missing.",
                })

        for field, expected_type in field_types.items():
            if field in out_dict:
                actual_type = _json_type(out_dict[field])
                if not _type_matches(actual_type, expected_type):
                    violations.append({
                        "path": field,
                        "message": (
                            f"Field '{field}' expected type '{expected_type}' "
                            f"but got '{actual_type}'."
                        ),
                    })

        passed = len(violations) == 0
        score = 1.0 if passed else max(0.0, 1.0 - (len(violations) * 0.2))
        threshold = scenario.scoring.threshold(self.id, 0.8) if scenario.scoring else 0.8

        summary = (
            "PASS: schema-compliance: output matches schema (1.0)"
            if passed
            else f"FAIL: schema-compliance: {len(violations)} violation(s) ({score:.2f})"
        )

        return ScoreResult(
            scorer_id=self.id,
            scorer_name=self.name,
            scoring_kind="deterministic",
            success=True,
            score=score,
            passed=score >= threshold,
            explanation=(
                "Candidate output conforms to expected schema."
                if passed
                else f"{len(violations)} schema violation(s) found."
            ),
            human_summary=summary,
            detail={
                "violation_count": len(violations),
                "violations": violations,
                "required_fields": required_fields,
                "field_types": field_types,
            },
        )
