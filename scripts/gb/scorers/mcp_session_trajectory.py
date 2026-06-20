"""Fake MCP session trajectory scorer — port of McpSessionTrajectoryScorer.cs.

Scores durable multi-turn fake-MCP sessions. Each turn has independent tool
expectations; aggregate detail surfaces trajectory-level repeated mistakes
(forbidden tool use across turns). Default threshold 0.8.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


@dataclass
class _ExpectedCall:
    tool: str
    argument_contains: dict[str, str]


@dataclass
class _ExpectedTurn:
    expected_calls: list[_ExpectedCall] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    final_response_contains: list[str] = field(default_factory=list)
    allow_bypass: bool = False
    expect_no_tool_calls: bool = False
    threshold: float = 0.8


class McpSessionTrajectoryScorer:
    id = "mcp-session-trajectory"
    name = "Fake MCP Session Trajectory Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        params = scenario.scoring.params(self.id) if scenario.scoring else {}
        expected_turns = _get_expected_turns(params)
        output = _extract_output(candidate_result)
        turns = output.get("turns") if (output and isinstance(output.get("turns"), list)) else None

        if turns is None:
            return ScoreResult(
                scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
                success=False, score=0, passed=False,
                error="Could not extract MCP session turns output.",
                human_summary="FAIL: mcp-session: no parseable turns output",
            )
        turns = [t if isinstance(t, dict) else {} for t in turns]

        turn_count = max(len(expected_turns), len(turns))
        turn_details: list[dict[str, Any]] = []
        score_sum = 0.0
        passed_turn_count = 0
        forbidden_use_count = 0
        no_calls_violation_count = 0

        for i in range(turn_count):
            expected = expected_turns[i] if i < len(expected_turns) else _ExpectedTurn()
            actual = turns[i] if i < len(turns) else {}
            tool_calls = actual.get("tool_calls") if isinstance(actual.get("tool_calls"), list) else []
            tool_calls = [c for c in tool_calls if isinstance(c, dict)]
            bypass_attempts = actual.get("bypass_attempts") if isinstance(actual.get("bypass_attempts"), list) else []
            bypass_attempts = [c for c in bypass_attempts if isinstance(c, dict)]
            final_response = actual.get("final_response") if isinstance(actual.get("final_response"), str) else ""

            matched = _count_matched(expected.expected_calls, tool_calls)
            arg_matches = _count_arg_matches(expected.expected_calls, tool_calls)
            final_matches = sum(1 for s in expected.final_response_contains if s.lower() in final_response.lower())
            forbidden_tool_used = any(
                _str(c, "tool") and _str(c, "tool").lower() in [f.lower() for f in expected.forbidden_tools]
                for c in tool_calls
            )
            bypass_violated = (not expected.allow_bypass) and len(bypass_attempts) > 0
            no_calls_violated = expected.expect_no_tool_calls and len(tool_calls) > 0

            if forbidden_tool_used:
                forbidden_use_count += 1
            if no_calls_violated:
                no_calls_violation_count += 1

            turn_score = 0.0
            if not forbidden_tool_used and not bypass_violated and not no_calls_violated:
                call_score = 1.0 if not expected.expected_calls else matched / len(expected.expected_calls)
                arg_score = 1.0 if not expected.expected_calls else arg_matches / len(expected.expected_calls)
                final_score = 1.0 if not expected.final_response_contains else final_matches / len(expected.final_response_contains)
                turn_score = 0.45 * call_score + 0.15 * arg_score + 0.25 + 0.15 * final_score

            turn_passed = turn_score >= expected.threshold
            if turn_passed:
                passed_turn_count += 1
            score_sum += turn_score

            turn_details.append({
                "turn_index": i + 1,
                "score": turn_score,
                "passed": turn_passed,
                "expected_call_count": len(expected.expected_calls),
                "matched_call_count": matched,
                "argument_match_count": arg_matches,
                "actual_call_count": len(tool_calls),
                "final_response_match_count": final_matches,
                "final_response_expected_count": len(expected.final_response_contains),
                "forbidden_tool_used": forbidden_tool_used,
                "bypass_violated": bypass_violated,
                "no_calls_violated": no_calls_violated,
            })

        score = score_sum / turn_count if turn_count else 0.0
        threshold = scenario.scoring.threshold(self.id, 0.8) if scenario.scoring else 0.8
        passed = score >= threshold and forbidden_use_count == 0 and no_calls_violation_count == 0

        bits: list[str] = []
        if forbidden_use_count > 0:
            bits.append(f"forbidden tool use on {forbidden_use_count} turn(s)")
        if no_calls_violation_count > 0:
            bits.append(f"unexpected tool calls on {no_calls_violation_count} turn(s)")
        if passed_turn_count < turn_count:
            bits.append(f"{passed_turn_count}/{turn_count} turns passed")
        summary = (
            f"PASS: mcp-session: {passed_turn_count}/{turn_count} turns passed ({score:.2f})"
            if passed
            else f"FAIL: mcp-session: {'; '.join(bits)} ({score:.2f})"
        )

        return ScoreResult(
            scorer_id=self.id, scorer_name=self.name, scoring_kind="deterministic",
            success=True, score=score, passed=passed, human_summary=summary,
            explanation=f"session turns passed {passed_turn_count}/{turn_count}; forbidden tool use count {forbidden_use_count}",
            detail={
                "turn_count": turn_count,
                "passed_turn_count": passed_turn_count,
                "forbidden_tool_use_count": forbidden_use_count,
                "no_calls_violation_count": no_calls_violation_count,
                "turns": turn_details,
            },
        )


def _get_expected_turns(params: dict[str, Any]) -> list[_ExpectedTurn]:
    value = params.get("turns")
    if not isinstance(value, list):
        return []
    turns: list[_ExpectedTurn] = []
    for turn in value:
        if not isinstance(turn, dict):
            continue
        turns.append(_ExpectedTurn(
            expected_calls=_get_expected_calls(turn, "expected_calls"),
            forbidden_tools=_str_list(turn, "forbidden_tools"),
            final_response_contains=_str_list(turn, "final_response_contains"),
            allow_bypass=_bool(turn, "allow_bypass", False),
            expect_no_tool_calls=_bool(turn, "expect_no_tool_calls", False),
            threshold=_num(turn, "threshold", 0.8),
        ))
    return turns


def _get_expected_calls(obj: dict[str, Any], key: str) -> list[_ExpectedCall]:
    value = obj.get(key)
    if not isinstance(value, list):
        return []
    calls: list[_ExpectedCall] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            continue
        contains: dict[str, str] = {}
        ac = item.get("argument_contains")
        if isinstance(ac, dict):
            for k, v in ac.items():
                contains[str(k)] = v if isinstance(v, str) else json.dumps(v)
        calls.append(_ExpectedCall(tool=tool, argument_contains=contains))
    return calls


def _count_matched(expected: list[_ExpectedCall], actual: list[dict[str, Any]]) -> int:
    actual_tools = {_str(a, "tool").lower() for a in actual}
    return sum(1 for e in expected if e.tool.lower() in actual_tools)


def _count_arg_matches(expected: list[_ExpectedCall], actual: list[dict[str, Any]]) -> int:
    count = 0
    for e in expected:
        for a in actual:
            if _str(a, "tool").lower() != e.tool.lower():
                continue
            args = a.get("arguments")
            args_text = json.dumps(args, default=str) if args is not None else ""
            if not e.argument_contains or all(
                key.lower() in args_text.lower() and val.lower() in args_text.lower()
                for key, val in e.argument_contains.items()
            ):
                count += 1
                break
    return count


def _extract_output(result: CandidateResult) -> dict[str, Any] | None:
    for src in (result.output, result.parsed_response):
        if isinstance(src, dict):
            return src
    raw = result.raw_response
    if isinstance(raw, str) and raw.strip():
        try:
            v = json.loads(raw)
            if isinstance(v, dict):
                return v
        except (ValueError, TypeError):
            pass
    return None


def _str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    return v if isinstance(v, str) else ""


def _str_list(d: dict[str, Any], key: str) -> list[str]:
    v = d.get(key)
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, str)]


def _bool(d: dict[str, Any], key: str, default: bool) -> bool:
    v = d.get(key)
    return v if isinstance(v, bool) else default


def _num(d: dict[str, Any], key: str, default: float) -> float:
    v = d.get(key)
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    return default
