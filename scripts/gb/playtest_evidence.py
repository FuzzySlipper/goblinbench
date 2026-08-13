"""Evidence contracts and pairwise adjudication for interactive playtests.

This module deliberately keeps the benchmark's claim small.  It validates the
operator/session/evidence envelope and, when a scenario supplies a known
expected terminal outcome, marks the cell behaviorally correct or incorrect.
It never turns that result into a universal model score.  Pairwise labels are
attached to the two matched cells after the run has collected both sides.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from .context import RunContext
from .models import CandidateResult, PerScenarioResult, Scenario, ScoreResult

PLAYTEST_SCORER_ID = "playtest-evidence"
PAIR_OUTCOMES = {"challenger_win", "luna_win", "tie", "invalid_pair"}
PLAYTEST_OUTCOMES = {"pass", "fail", "uncertain", "infrastructure_error"}
REQUIRED_LOCAL_TOOL_PROFILE = "vision_playtester"
ALLOWED_TOOL_NAMES = {
    "playtest_start",
    "playtest_observe",
    "playtest_act",
    "playtest_finish",
    "deliver_completion_md",
    "rusty_crew_help",
}

# The native profile already exposes typed schemas, but the broker deliberately
# keeps additional JSON fields for forward compatibility.  Re-check the
# captured call arguments here so a future schema expansion cannot silently
# turn this benchmark into a DOM/state/eval lane.
FORBIDDEN_ARGUMENT_KEYS = {
    "dom",
    "storage",
    "accessibility",
    "expressions",
    "expression",
    "eval",
    "evaluate",
    "javascript",
    "cdp",
    "network",
    "websocket",
    "web_socket",
    "page_state",
    "game_state",
    "application_state",
    "hidden_state",
    "inspect",
    "selector",
}


def load_json(path: str | os.PathLike[str]) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_string(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _forbidden_argument_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            key_folded = key_text.casefold()
            current = f"{path}.{key_text}" if path else key_text
            if key_folded in FORBIDDEN_ARGUMENT_KEYS:
                found.append(current)
            found.extend(_forbidden_argument_keys(nested, current))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_forbidden_argument_keys(nested, f"{path}[{index}]"))
    return found


def _candidate_evidence(result: CandidateResult) -> dict[str, Any]:
    output = _dict(result.output)
    evidence = _dict(output.get("playtest_evidence"))
    if evidence:
        return evidence
    # Imported/replayed cells may only have their evidence in parsed_response.
    return _dict(_dict(result.parsed_response).get("playtest_evidence"))


def _revision_from_index(index: dict[str, Any]) -> str:
    return _first_string(_dict(index.get("revision")), "commit_sha", "commitSha").lower()


def _artifact_refs(index: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in _list(index.get("artifacts")):
        if isinstance(value, str) and value.strip():
            refs.append(value.strip())
    for observation in _list(index.get("observations")):
        observation_map = _dict(observation)
        for key in ("screenshot", "trace", "timeline"):
            value = observation_map.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
        for value in _list(observation_map.get("frames")):
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
    assertions = _list(evidence.get("assertions"))
    if not assertions:
        assertions = _list(_dict(_dict(index.get("metadata")).get("assertions")))
    for assertion in assertions:
        value = _first_string(_dict(assertion), "artifact", "artifact_ref", "artifactRef")
        if value:
            # Finish annotations often use a semicolon-separated list.  Only
            # retain path-looking tokens here; prose remains in the report.
            for token in value.split(";"):
                token = token.strip()
                if "/" in token or ".png" in token or ".json" in token:
                    refs.append(token)
    seen: set[str] = set()
    return [ref for ref in refs if not (ref in seen or seen.add(ref))]


def _resolve_index_path(evidence: dict[str, Any]) -> Path | None:
    raw = _first_string(evidence, "evidence_index", "index_path", "indexPath")
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def _mutation_proof_errors(
    proof_path: str,
    expected_revision: str,
    expected_sha256: str,
) -> list[str]:
    """Validate generated mutation-proof metadata when it is JSON-shaped."""

    errors: list[str] = []
    path = Path(proof_path).expanduser()
    try:
        content = path.read_bytes()
    except OSError as exc:
        return [f"mutation proof path is unreadable: {exc}"]
    observed_sha256 = hashlib.sha256(content).hexdigest()
    if expected_sha256 and observed_sha256 != expected_sha256.lower():
        errors.append("mutation proof SHA-256 does not match the retained proof")
    if path.suffix.lower() != ".json":
        return errors
    try:
        document = _dict(json.loads(content.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [*errors, "mutation proof JSON is unreadable"]
    mutation_revision = _first_string(document, "mutation_revision", "mutationRevision").lower()
    if mutation_revision and mutation_revision != expected_revision.lower():
        errors.append("mutation proof mutation_revision disagrees with the scenario revision")
    if document.get("worktree_clean") is not True:
        errors.append("mutation proof does not certify a clean mutation worktree")
    checks = _list(document.get("source_checks"))
    if checks and any(_dict(check).get("passed") is not True for check in checks):
        errors.append("mutation proof contains a failed source contract")
    return errors


def _read_index(evidence: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    inline = evidence.get("evidence_index_data")
    if isinstance(inline, dict):
        return inline, None
    path = _resolve_index_path(evidence)
    if path is None:
        return {}, None
    try:
        value = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}, str(path)
    return (_dict(value), str(path))


def evaluate_playtest_evidence(
    scenario: Scenario,
    result: CandidateResult,
    context: RunContext | None = None,
) -> dict[str, Any]:
    """Return a deterministic, non-scalar evaluation of one playtest cell."""

    evidence = _candidate_evidence(result)
    output = _dict(result.output)
    params = scenario.scoring.params(PLAYTEST_SCORER_ID) if scenario.scoring else {}
    expected_revision = _first_string(
        params,
        "expected_revision",
    ) or _first_string(scenario.input, "expected_revision") or _first_string(evidence, "expected_revision")
    expected_outcome = _first_string(
        params,
        "expected_outcome",
    ) or _first_string(scenario.input, "expected_outcome")
    pair_id = _first_string(evidence, "pair_id") or _first_string(output, "pair_id") or _first_string(scenario.input, "pair_id")
    pair_role = _first_string(evidence, "pair_role") or _first_string(output, "pair_role")
    expected_cell_id = _first_string(params, "cell_id") or _first_string(scenario.input, "cell_id")
    cell_id = _first_string(evidence, "cell_id") or _first_string(output, "cell_id")
    cell_class = _first_string(params, "cell_class") or _first_string(scenario.input, "cell_class")
    mutation_proof = _first_string(evidence, "mutation_proof") or _first_string(output, "mutation_proof")
    mutation_proof_path = _first_string(evidence, "mutation_proof_path") or _first_string(output, "mutation_proof_path")
    mutation_proof_sha256 = _first_string(evidence, "mutation_proof_sha256") or _first_string(output, "mutation_proof_sha256")
    defect_family = (
        _first_string(evidence, "defect_family")
        or _first_string(output, "defect_family")
        or _first_string(params, "defect_family")
        or _first_string(scenario.input, "defect_family")
    )
    required_profile = (
        _first_string(params, "required_local_tool_profile")
        or _first_string(scenario.input, "required_local_tool_profile")
        or REQUIRED_LOCAL_TOOL_PROFILE
    )
    errors: list[str] = []
    warnings: list[str] = []

    finish_outcome = _first_string(evidence, "finish_outcome", "outcome")
    if finish_outcome not in PLAYTEST_OUTCOMES:
        errors.append("missing or invalid playtest_finish outcome")

    session_id = _first_string(evidence, "session_id", "playtest_session_id")
    if not session_id:
        errors.append("playtest session id is missing")
    if not expected_cell_id:
        errors.append("scorer-side cell_id is missing from the scenario contract")
    elif cell_id != expected_cell_id:
        errors.append(f"worker cell identity {cell_id or '<missing>'!r} does not match scorer cell {expected_cell_id!r}")
    if cell_class not in {"known_good", "mutation"}:
        errors.append("cell_class must be known_good or mutation")
    elif cell_class == "mutation" and not mutation_proof:
        errors.append("mutation cell has no retained mutation-proof handle")
    if cell_class == "mutation" and mutation_proof_path:
        if mutation_proof_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", mutation_proof_sha256):
            errors.append("mutation proof SHA-256 is not a 64-character hex digest")
        errors.extend(
            _mutation_proof_errors(
                mutation_proof_path,
                expected_revision,
                mutation_proof_sha256,
            )
        )

    index, index_path = _read_index(evidence)
    if not index:
        errors.append("authoritative playtest evidence index is unreadable or missing")
    if index_path:
        evidence["evidence_index"] = index_path
        expected_index_hash = _first_string(evidence, "evidence_index_sha256")
        if expected_index_hash:
            try:
                observed_index_hash = hashlib.sha256(Path(index_path).read_bytes()).hexdigest()
            except OSError:
                observed_index_hash = ""
            if observed_index_hash != expected_index_hash.lower():
                errors.append("evidence index SHA-256 does not match the retained index")
        else:
            observed_index_hash = ""
    else:
        observed_index_hash = ""
    index_revision = _revision_from_index(index)
    if not expected_revision:
        errors.append("expected revision is missing from the scenario contract")
    elif index_revision != expected_revision.lower():
        errors.append(
            f"evidence index revision {index_revision or '<missing>'} does not match expected {expected_revision.lower()}"
        )

    index_status = _first_string(index, "status")
    if finish_outcome and index_status and finish_outcome != index_status:
        errors.append(f"finish outcome {finish_outcome!r} disagrees with index status {index_status!r}")
    cleanup = _dict(index.get("cleanup"))
    cleanup_required = ("browser_closed", "driver_stopped")
    if finish_outcome != "infrastructure_error":
        missing_cleanup = [key for key in cleanup_required if cleanup.get(key) is not True]
        if missing_cleanup:
            errors.append(f"playtest cleanup is incomplete: {missing_cleanup}")

    revision_binding = _dict(evidence.get("revision_binding"))
    if expected_revision and revision_binding:
        observed = _first_string(revision_binding, "observed", "observed_revision", "observedRevision").lower()
        expected = _first_string(revision_binding, "expected", "expected_revision", "expectedRevision").lower()
        if expected and expected != expected_revision.lower():
            errors.append("broker revision binding expected SHA disagrees with scenario")
        if observed and observed != expected_revision.lower():
            errors.append("broker revision binding observed SHA disagrees with scenario")

    profile_id = _first_string(evidence, "local_tool_profile_id", "localToolProfileId")
    environment_profile = _dict(_dict(result.environment).get("profile"))
    profile_id = profile_id or _first_string(environment_profile, "local_tool_profile_id", "localToolProfileId")
    if profile_id != required_profile:
        errors.append(f"restricted profile readback {profile_id or '<missing>'!r} is not {required_profile!r}")

    tool_calls = _list(evidence.get("tool_calls"))
    forbidden_tools = sorted({
        _first_string(_dict(call), "tool_name", "toolName")
        for call in tool_calls
        if _first_string(_dict(call), "tool_name", "toolName")
        and _first_string(_dict(call), "tool_name", "toolName") not in ALLOWED_TOOL_NAMES
    })
    if forbidden_tools:
        errors.append(f"profile emitted disallowed tool calls: {forbidden_tools}")
    forbidden_argument_paths = sorted({
        path
        for call in tool_calls
        for path in _forbidden_argument_keys(_dict(call).get("arguments"))
    })
    if forbidden_argument_paths:
        errors.append(
            "playtest calls contained forbidden DOM/state/eval fields: "
            f"{forbidden_argument_paths[:8]}"
        )

    refs = _artifact_refs(index, evidence)
    assertions = _list(evidence.get("assertions"))
    if not assertions:
        assertions = _list(_dict(_dict(index.get("metadata")).get("assertions")))
    assertion_passes = [
        bool(_dict(assertion).get("pass"))
        for assertion in assertions
        if isinstance(assertion, dict) and isinstance(_dict(assertion).get("pass"), bool)
    ]
    failed_assertions = sum(1 for passed in assertion_passes if not passed)
    if not assertion_passes:
        errors.append("playtest_finish/evidence index has no boolean assertions")
    if finish_outcome == "fail" and assertion_passes and failed_assertions == 0:
        errors.append("fail outcome has no failed behavioral assertion")
    has_screenshot = any(ref.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) for ref in refs)
    if not refs:
        errors.append("evidence index has no retained artifact references")
    if not has_screenshot:
        errors.append("evidence index has no screenshot/frame artifact")

    requires_sequence = bool(
        params.get("requires_sequence", scenario.input.get("requires_sequence", False))
    )
    observation_count = len(_list(index.get("observations")))
    frame_count = sum(len(_list(_dict(obs).get("frames"))) for obs in _list(index.get("observations")))
    if requires_sequence and observation_count < 2 and frame_count < 2:
        errors.append("transition/motion claim has no observation sequence or frame burst")

    max_actions = params.get("max_actions", scenario.input.get("max_actions"))
    actions_used = evidence.get("actions_used", evidence.get("actionsUsed"))
    if max_actions is not None and actions_used is not None:
        try:
            if int(actions_used) > int(max_actions):
                errors.append(f"reported actions {actions_used} exceed budget {max_actions}")
        except (TypeError, ValueError):
            errors.append("reported action count is not an integer")

    # An infrastructure terminal is a valid operator completion, but it is not
    # a behaviorally comparable cell.  Its evidence is retained for diagnosis.
    if finish_outcome == "infrastructure_error":
        warnings.append("infrastructure_error is retained but cannot enter pairwise adjudication")

    evidence_valid = not errors and finish_outcome != "infrastructure_error"
    if expected_outcome in PLAYTEST_OUTCOMES and evidence_valid:
        if expected_outcome == "pass":
            behavior_matches = finish_outcome == "pass" and failed_assertions == 0
        elif expected_outcome == "fail":
            behavior_matches = finish_outcome == "fail" and failed_assertions > 0
        else:
            behavior_matches = finish_outcome == expected_outcome
        behavioral_status = "correct" if behavior_matches else "incorrect"
    elif expected_outcome:
        behavioral_status = "invalid"
    else:
        behavioral_status = "unadjudicated"
        warnings.append("scenario has no expected outcome; pairwise result requires human/judge adjudication")

    return {
        "contract_version": "goblinbench.interactive-playtest/v1",
        "pair_id": pair_id,
        "pair_role": pair_role,
        "cell_id": cell_id,
        "expected_cell_id": expected_cell_id,
        "cell_class": cell_class,
        "mutation_proof": mutation_proof,
        "mutation_proof_path": mutation_proof_path,
        "mutation_proof_sha256": mutation_proof_sha256,
        "defect_family": defect_family,
        "defect_family_claim": _first_string(
            evidence,
            "defect_family_claim",
            "claimed_defect_family",
        ),
        "session_id": session_id,
        "finish_outcome": finish_outcome,
        "expected_outcome": expected_outcome,
        "behavioral_status": behavioral_status,
        "evidence_valid": evidence_valid,
        "comparison_eligible": evidence_valid and behavioral_status in {"correct", "incorrect"},
        "errors": errors,
        "warnings": warnings,
        "expected_revision": expected_revision.lower(),
        "observed_revision": index_revision,
        "evidence_index": index_path or _first_string(evidence, "evidence_index", "index_path", "indexPath"),
        "evidence_index_sha256": _first_string(evidence, "evidence_index_sha256") or observed_index_hash,
        "evidence_archive": evidence.get("evidence_archive"),
        "artifact_refs": refs,
        "observation_count": observation_count,
        "frame_count": frame_count,
        "assertion_count": len(assertion_passes),
        "failed_assertion_count": failed_assertions,
        "actions_used": actions_used,
        "required_local_tool_profile": required_profile,
        "local_tool_profile_id": profile_id,
        "forbidden_tools": forbidden_tools,
        "forbidden_argument_paths": forbidden_argument_paths,
        "cleanup": cleanup,
        "pair_outcome": None,
        "context_run_id": context.run_id if context else None,
    }


class PlaytestEvidenceScorer:
    id = PLAYTEST_SCORER_ID
    name = "Interactive Playtest Evidence Contract"

    def score(
        self,
        scenario: Scenario,
        candidate: Any,
        candidate_result: CandidateResult,
        context: RunContext,
    ) -> ScoreResult:
        detail = evaluate_playtest_evidence(scenario, candidate_result, context)
        valid = bool(detail["evidence_valid"])
        outcome = detail.get("finish_outcome") or "invalid"
        status = detail.get("behavioral_status") or "unadjudicated"
        summary = (
            f"{'VALID' if valid else 'INVALID'} interactive evidence; "
            f"terminal={outcome}; behavioral={status}; pair={detail.get('pair_id') or 'unpaired'}"
        )
        if detail["errors"]:
            summary += "; " + "; ".join(str(error) for error in detail["errors"][:2])
        return ScoreResult(
            scorer_id=self.id,
            scorer_name=self.name,
            scoring_kind="contract",
            success=True,
            score=None,
            passed=valid,
            human_summary=summary,
            explanation="Structural evidence validity only; no universal model-strength score is emitted.",
            detail=detail,
        )


def _playtest_score(result: CandidateResult) -> ScoreResult | None:
    for score in result.scores:
        if score.scorer_id == PLAYTEST_SCORER_ID:
            return score
    return None


def apply_pairwise_outcomes(scenario_result: PerScenarioResult) -> list[dict[str, Any]]:
    """Attach a relational label to each matched pair in a scenario result."""

    grouped: dict[str, list[CandidateResult]] = {}
    for result in scenario_result.candidate_results:
        score = _playtest_score(result)
        if score is None:
            continue
        pair_id = str(score.detail.get("pair_id") or "").strip()
        if pair_id:
            grouped.setdefault(pair_id, []).append(result)

    decisions: list[dict[str, Any]] = []
    for pair_id, members in sorted(grouped.items()):
        indexed: dict[str, CandidateResult] = {}
        for member in members:
            score = _playtest_score(member)
            role = str((score.detail if score else {}).get("pair_role") or "").strip().lower()
            if role in {"incumbent", "luna"} and "incumbent" not in indexed:
                indexed["incumbent"] = member
            elif role == "challenger" and "challenger" not in indexed:
                indexed["challenger"] = member

        incumbent = indexed.get("incumbent")
        challenger = indexed.get("challenger")
        inc_score = _playtest_score(incumbent) if incumbent else None
        chal_score = _playtest_score(challenger) if challenger else None
        inc_detail = inc_score.detail if inc_score else {}
        chal_detail = chal_score.detail if chal_score else {}
        if not incumbent or not challenger or not inc_score or not chal_score:
            outcome = "invalid_pair"
            reason = "pair requires exactly one incumbent/Luna and one challenger cell"
        elif not inc_detail.get("comparison_eligible") or not chal_detail.get("comparison_eligible"):
            outcome = "invalid_pair"
            reason = "one or both cells lack contract-valid adjudicable evidence"
        elif inc_detail.get("behavioral_status") == chal_detail.get("behavioral_status"):
            outcome = "tie"
            reason = "matched cells have the same behavioral result"
        elif chal_detail.get("behavioral_status") == "correct":
            outcome = "challenger_win"
            reason = "challenger matched the scenario outcome and Luna did not"
        else:
            outcome = "luna_win"
            reason = "Luna matched the scenario outcome and challenger did not"

        decision = {
            "pair_id": pair_id,
            "scenario_id": scenario_result.scenario_id,
            "outcome": outcome,
            "reason": reason,
            "incumbent_candidate_id": incumbent.candidate_id if incumbent else None,
            "challenger_candidate_id": challenger.candidate_id if challenger else None,
            "members": [member.candidate_id for member in members],
        }
        decisions.append(decision)
        for member in members:
            score = _playtest_score(member)
            if score is not None:
                score.detail["pair_outcome"] = outcome
                score.detail["pair_decision"] = decision
            output = _dict(member.output)
            output["pairwise"] = decision
            member.output = output
            if member.artifact_directory:
                try:
                    path = Path(member.artifact_directory) / "pairwise.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                except OSError:
                    # The DB score detail remains authoritative if scratch
                    # artifact writing fails.
                    pass
    return decisions


def _safe_relative_path(root: Path, value: str) -> Path | None:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def archive_selected_evidence(
    evidence_index_path: str | os.PathLike[str],
    archive_root: str | os.PathLike[str],
    selected_refs: Iterable[str] = (),
) -> dict[str, Any]:
    """Copy the index and selected screenshots into non-ring-buffer storage."""

    source = Path(evidence_index_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    index_bytes = source.read_bytes()
    digest = hashlib.sha256(index_bytes).hexdigest()
    destination = Path(archive_root).expanduser().resolve() / digest
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "playtest-index.json").write_bytes(index_bytes)
    try:
        index = _dict(json.loads(index_bytes.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        index = {}
    refs = [str(ref).strip() for ref in selected_refs if str(ref).strip()]
    if not refs:
        # Replayed indexes may not have a runner-side evidence envelope.  Use
        # the assertion ledger as the fallback selection, not the complete
        # ring-buffer artifact list.
        for assertion in _list(_dict(index.get("metadata")).get("assertions")):
            value = _first_string(_dict(assertion), "artifact", "artifact_ref", "artifactRef")
            if value:
                refs.extend(token.strip() for token in value.split(";") if token.strip())
    if not refs:
        # Keep the helper useful for tiny synthetic indexes and invalid-cell
        # diagnostics while avoiding a full video/frame copy in real packets.
        refs = [
            str(value).strip()
            for value in _list(index.get("artifacts"))
            if isinstance(value, str)
            and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        ]
    refs = list(dict.fromkeys(refs))
    copied: list[str] = ["playtest-index.json"]
    source_root = source.parent.resolve()
    for ref in refs:
        ref = str(ref).strip()
        if not ref or ref == "playtest-index.json":
            continue
        # Assertion prose can contain a path plus surrounding text.  Do not
        # copy arbitrary paths; only exact relative artifact references stay.
        ref_path = Path(ref).expanduser()
        if ref_path.is_absolute():
            try:
                ref = str(ref_path.resolve().relative_to(source_root))
            except ValueError:
                continue
        if ref == "playtest-index.json":
            continue
        candidate = _safe_relative_path(source_root, ref)
        if candidate is None or not candidate.is_file():
            continue
        rel = candidate.relative_to(source_root)
        target = destination / "artifacts" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
        copied.append(str(Path("artifacts") / rel))
    manifest = {
        "schema_version": "goblinbench.playtest-evidence-archive/v1",
        "index_sha256": digest,
        "source_index": str(source),
        "files": copied,
        "revision": _revision_from_index(index),
    }
    (destination / "archive-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"archive_dir": str(destination), "archive_manifest": manifest}
