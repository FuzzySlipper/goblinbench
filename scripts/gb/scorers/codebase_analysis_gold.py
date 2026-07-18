"""Deterministic gold-ledger scorer for read-only codebase analysis."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult


_SEVERITY_WEIGHT = {"critical": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0, "info": 0.5}
_MATCH_THRESHOLD = 0.82
_GOOD_MATCH_THRESHOLD = 0.95


class CodebaseAnalysisGoldScorer:
    id = "codebase-analysis-gold"
    name = "Codebase Analysis Gold-Ledger Scorer"

    def score(
        self,
        scenario: Scenario,
        candidate: CandidateConfig,
        candidate_result: CandidateResult,
        context: RunContext,
    ) -> ScoreResult:
        output = candidate_result.output if isinstance(candidate_result.output, dict) else {}
        findings = output.get("findings")
        if not isinstance(findings, list):
            return self._failed("analysis_parse_failed", "No parseable findings array was produced.")
        all_findings = [item for item in findings if isinstance(item, dict)][:24]
        params = scenario.scoring.params(self.id) if scenario.scoring else {}
        max_findings = _positive_int(params.get("max_findings"), 16)
        findings = all_findings[:max_findings]
        if not findings:
            return self._failed("analysis_no_findings", "The candidate produced no structured findings.")

        analysis_evidence = output.get("analysis_evidence")
        if isinstance(analysis_evidence, dict) and analysis_evidence.get("passed") is False:
            return self._failed(
                "analysis_tool_evidence_missing",
                f"Read-only analysis evidence failed: {analysis_evidence.get('violations')}",
            )

        fixture_root = _fixture_root(context, params)
        try:
            gold_doc = _load_json(fixture_root, params, "gold_ledger")
            decoy_doc = _load_json(fixture_root, params, "decoys")
            signals_doc = _load_json(fixture_root, params, "signals")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return ScoreResult(
                scorer_id=self.id,
                scorer_name=self.name,
                scoring_kind="deterministic",
                success=False,
                score=0.0,
                passed=False,
                error=f"Could not load codebase-analysis scoring fixture: {exc}",
                human_summary="FAIL: codebase-analysis: scorer fixture unavailable",
            )

        gold = [item for item in gold_doc.get("issues", []) if isinstance(item, dict)]
        decoys = [item for item in decoy_doc.get("decoys", []) if isinstance(item, dict)]
        issue_signals = signals_doc.get("issues") if isinstance(signals_doc.get("issues"), dict) else {}
        decoy_signals = signals_doc.get("decoys") if isinstance(signals_doc.get("decoys"), dict) else {}
        packet_sections = _packet_sections(
            fixture_root / _safe_filename(params.get("analysis_file"), "analysis_file")
        )

        pair_scores: list[tuple[float, int, str, int, int]] = []
        for finding_index, finding in enumerate(findings):
            for issue in gold:
                issue_id = str(issue.get("id") or "")
                score, path_hits, signal_hits = _match_score(
                    finding, issue, _signal_groups(issue_signals.get(issue_id)), packet_sections
                )
                if score >= _MATCH_THRESHOLD:
                    pair_scores.append((score, finding_index, issue_id, path_hits, signal_hits))

        assignments: dict[int, tuple[str, float, int, int]] = {}
        used_issues: set[str] = set()
        for score, finding_index, issue_id, path_hits, signal_hits in sorted(
            pair_scores, reverse=True
        ):
            if finding_index in assignments or issue_id in used_issues:
                continue
            assignments[finding_index] = (issue_id, score, path_hits, signal_hits)
            used_issues.add(issue_id)

        decoy_hits: list[dict[str, str]] = []
        evaluations: list[dict[str, Any]] = []
        for index, finding in enumerate(findings):
            assigned = assignments.get(index)
            if assigned:
                issue_id, quality, path_hits, signal_hits = assigned
                evaluations.append({
                    "title": _text(finding.get("title")) or f"finding-{index + 1}",
                    "match_gold_id": issue_id,
                    "match_quality": (
                        "good_match" if quality >= _GOOD_MATCH_THRESHOLD else "partial_match"
                    ),
                    "match_score": round(quality, 4),
                    "path_hit_count": path_hits,
                    "signal_group_hit_count": signal_hits,
                    "is_decoy_hit": False,
                })
                continue
            decoy_id = _best_decoy(finding, decoys, decoy_signals, packet_sections)
            if decoy_id:
                decoy_hits.append({
                    "title": _text(finding.get("title")) or f"finding-{index + 1}",
                    "decoy_id": decoy_id,
                })
            evaluations.append({
                "title": _text(finding.get("title")) or f"finding-{index + 1}",
                "match_gold_id": None,
                "match_quality": "no_match",
                "match_score": 0.0,
                "path_hit_count": 0,
                "signal_group_hit_count": 0,
                "is_decoy_hit": bool(decoy_id),
                "decoy_id": decoy_id,
            })

        gold_by_id = {str(item.get("id")): item for item in gold}
        total_weight = sum(_issue_weight(item) for item in gold)
        recall_credit = 0.0
        severity_scores: list[float] = []
        for index, (issue_id, quality, _path_hits, _signal_hits) in assignments.items():
            issue = gold_by_id[issue_id]
            credit = 1.0 if quality >= _GOOD_MATCH_THRESHOLD else 0.7
            recall_credit += _issue_weight(issue) * credit
            severity_scores.append(_severity_score(findings[index], issue))
        gold_recall = recall_credit / total_weight if total_weight else 1.0
        # The fixture intentionally contains legitimate issues beyond the gold
        # ledger. Unmatched findings are therefore unclassified, not automatic
        # false positives. Precision is measured only against known decoys.
        classified_count = len(assignments) + len(decoy_hits)
        precision = len(assignments) / classified_count if classified_count else 0.0
        evidence_quality = sum(_evidence_quality(item) for item in findings) / len(findings)
        fix_quality = sum(_fix_quality(item) for item in findings) / len(findings)
        severity_calibration = sum(severity_scores) / len(severity_scores) if severity_scores else 0.0
        raw_score = (
            0.65 * gold_recall
            + 0.10 * precision
            + 0.12 * evidence_quality
            + 0.08 * fix_quality
            + 0.05 * severity_calibration
        )
        count_penalty = min(0.10, 0.02 * max(0, len(all_findings) - max_findings))
        score = max(0.0, raw_score - min(0.30, 0.10 * len(decoy_hits)) - count_penalty)
        threshold = scenario.scoring.threshold(self.id, 0.45) if scenario.scoring else 0.45
        passed = score >= threshold
        missed_ids = [str(item.get("id")) for item in gold if str(item.get("id")) not in used_issues]
        failure_categories: list[str] = []
        if gold_recall < 0.35:
            failure_categories.append("low_gold_recall")
        if evidence_quality < 0.60:
            failure_categories.append("weak_code_evidence")
        if decoy_hits:
            failure_categories.append("architecture_decoy_hit")
        if len(all_findings) > max_findings:
            failure_categories.append("finding_count_exceeded")

        summary = (
            f"{'PASS' if passed else 'FAIL'}: codebase-analysis: "
            f"matched {len(assignments)}/{len(gold)} gold issues, "
            f"{len(decoy_hits)} decoy hit(s), score {score:.2f}"
        )
        return ScoreResult(
            scorer_id=self.id,
            scorer_name=self.name,
            scoring_kind="deterministic",
            success=True,
            score=score,
            passed=passed,
            human_summary=summary,
            explanation=(
                f"severity-weighted recall {gold_recall:.2f}; precision {precision:.2f}; "
                f"evidence {evidence_quality:.2f}; fix quality {fix_quality:.2f}; "
                f"severity calibration {severity_calibration:.2f}"
            ),
            detail={
                "gold_issue_count": len(gold),
                "candidate_finding_count": len(findings),
                "candidate_finding_count_before_limit": len(all_findings),
                "max_findings": max_findings,
                "matched_gold_count": len(assignments),
                "matched_gold_ids": sorted(used_issues),
                "missed_gold_ids": missed_ids,
                "gold_recall": round(gold_recall, 4),
                "precision": round(precision, 4),
                "evidence_quality_score": round(evidence_quality, 4),
                "fix_quality_score": round(fix_quality, 4),
                "severity_calibration_score": round(severity_calibration, 4),
                "raw_score": round(raw_score, 4),
                "finding_count_penalty": round(count_penalty, 4),
                "decoy_hit_count": len(decoy_hits),
                "decoy_hits": decoy_hits,
                "unclassified_finding_count": len(findings) - classified_count,
                "evaluations": evaluations,
                "failure_categories": failure_categories,
            },
        )

    def _failed(self, category: str, explanation: str) -> ScoreResult:
        return ScoreResult(
            scorer_id=self.id,
            scorer_name=self.name,
            scoring_kind="deterministic",
            success=True,
            score=0.0,
            passed=False,
            human_summary=f"FAIL: codebase-analysis: {explanation}",
            explanation=explanation,
            detail={"failure_categories": [category]},
        )


def _fixture_root(context: RunContext, params: dict[str, Any]) -> Path:
    repo_root = Path(context.repo_root or Path(__file__).resolve().parents[3])
    fixture_case = _text(params.get("fixture_case"))
    if not fixture_case or Path(fixture_case).name != fixture_case:
        raise ValueError("codebase-analysis fixture_case must be one safe directory name")
    return repo_root / "fixtures" / "codebase-analysis" / fixture_case


def _load_json(root: Path, params: dict[str, Any], key: str) -> dict[str, Any]:
    name = _safe_filename(params.get(key), key)
    value = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{key} must contain a JSON object")
    return value


def _safe_filename(value: Any, key: str) -> str:
    name = _text(value)
    if not name or Path(name).name != name:
        raise ValueError(f"{key} must be one safe fixture filename")
    return name


def _positive_int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _packet_sections(path: Path) -> list[tuple[int, str]]:
    sections: list[tuple[int, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = re.match(r"^##\s+((?:src|tests|docs)/\S+)$", line.strip())
        if match:
            sections.append((line_number, match.group(1)))
    return sections


def _signal_groups(value: Any) -> list[list[str]]:
    if not isinstance(value, dict) or not isinstance(value.get("signal_groups"), list):
        return []
    return [
        [str(item).casefold() for item in group if isinstance(item, str) and item.strip()]
        for group in value["signal_groups"]
        if isinstance(group, list)
    ]


def _match_score(
    finding: dict[str, Any],
    target: dict[str, Any],
    signal_groups: list[list[str]],
    packet_sections: list[tuple[int, str]],
) -> tuple[float, int, int]:
    finding_paths = _finding_paths(finding, packet_sections)
    target_paths = [str(path) for path in target.get("planted_in", []) if isinstance(path, str)]
    path_hits = sum(1 for path in finding_paths if any(_same_path(path, target_path) for target_path in target_paths))
    if path_hits == 0:
        return 0.0, 0, 0
    haystack = _finding_text(finding)
    signal_hits = sum(1 for group in signal_groups if any(signal in haystack for signal in group))
    if signal_hits == 0:
        return 0.0, path_hits, 0
    signal_fraction = signal_hits / max(1, len(signal_groups))
    return 0.55 + 0.45 * signal_fraction, path_hits, signal_hits


def _best_decoy(
    finding: dict[str, Any],
    decoys: list[dict[str, Any]],
    signals: dict[str, Any],
    packet_sections: list[tuple[int, str]],
) -> str | None:
    best: tuple[float, str] | None = None
    for decoy in decoys:
        decoy_id = str(decoy.get("id") or "")
        score, _path_hits, _signal_hits = _match_score(
            finding, decoy, _signal_groups(signals.get(decoy_id)), packet_sections
        )
        if score >= _MATCH_THRESHOLD and (best is None or score > best[0]):
            best = (score, decoy_id)
    return best[1] if best else None


def _finding_paths(
    finding: dict[str, Any], packet_sections: list[tuple[int, str]]
) -> list[str]:
    evidence = finding.get("evidence")
    if not isinstance(evidence, list):
        return []
    paths: list[str] = []
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = str(item["path"])
        paths.append(path)
        if Path(path).name.casefold() != "repo-packet.md":
            continue
        line_numbers = [int(value) for value in re.findall(r"\d+", _text(item.get("lines")))]
        if not line_numbers:
            continue
        low, high = min(line_numbers), max(line_numbers)
        for start, source_path in packet_sections:
            if start > high:
                break
            next_starts = [candidate for candidate, _ in packet_sections if candidate > start]
            end = (next_starts[0] - 1) if next_starts else 10**9
            if high >= start and low <= end:
                paths.append(source_path)
    return paths


def _finding_text(finding: dict[str, Any]) -> str:
    return " ".join(
        re.sub(r"\s+", " ", value).casefold()
        for value in _walk_strings(finding)
    )


def _walk_strings(value: Any):  # type: ignore[no-untyped-def]
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _same_path(left: str, right: str) -> bool:
    a = _canonical_path(left)
    b = _canonical_path(right)
    return a == b or a.endswith("/" + b) or b.endswith("/" + a)


def _canonical_path(value: str) -> str:
    path = value.replace("\\", "/").removeprefix("./").casefold()
    # Models often render C# namespace folders with dots even when the packet
    # heading uses path separators. Preserve the real DenCore.Service project
    # name while normalizing domain-layer namespace variants.
    return re.sub(r"/dencore\.(models|data|services|llm|mcp)/", r"/dencore/\1/", path)


def _evidence_quality(finding: dict[str, Any]) -> float:
    evidence = finding.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return 0.0
    best = 0.0
    for item in evidence:
        if not isinstance(item, dict):
            continue
        score = 0.0
        if _text(item.get("path")):
            score += 0.4
        if _text(item.get("lines")):
            score += 0.25
        if len(_text(item.get("quote"))) >= 12:
            score += 0.35
        best = max(best, score)
    return best


def _fix_quality(finding: dict[str, Any]) -> float:
    length = len(_text(finding.get("fix")))
    if length >= 40:
        return 1.0
    if length >= 15:
        return 0.5
    return 0.0


def _severity_score(finding: dict[str, Any], issue: dict[str, Any]) -> float:
    order = ["info", "low", "medium", "high", "critical"]
    candidate_severity = _text(finding.get("severity")).casefold()
    gold_severity = _text(issue.get("severity")).casefold()
    if candidate_severity not in order or gold_severity not in order:
        return 0.0
    distance = abs(order.index(candidate_severity) - order.index(gold_severity))
    return 1.0 if distance == 0 else (0.5 if distance == 1 else 0.0)


def _issue_weight(issue: dict[str, Any]) -> float:
    return _SEVERITY_WEIGHT.get(_text(issue.get("severity")).casefold(), 1.0)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
