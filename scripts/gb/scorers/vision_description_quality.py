"""Vision description-quality scorer for chaotic visual-inspect scenarios.

Scores structured visual descriptions against a scenario-owned gold manifest. The
intent is not perfect caption equality; it is to separate useful, concrete,
region-aware descriptions from vague or hallucinated ones.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ..context import RunContext
from ..models import CandidateConfig, CandidateResult, Scenario, ScoreResult
from ..runners import _openai

_WORD_RE = re.compile(r"[a-z0-9]+")
_GENERIC_PHRASES = (
    "many things",
    "various items",
    "several things",
    "lots of things",
    "a cluttered image",
    "a busy image",
    "stuff",
    "objects",
    "items",
)
_UNCERTAINTY_WORDS = (
    "uncertain",
    "unclear",
    "ambiguous",
    "possibly",
    "maybe",
    "might",
    "appears",
    "seems",
    "hard to tell",
    "partly occluded",
    "occluded",
    "blurry",
)


class VisionDescriptionQualityScorer:
    id = "vision-description-quality"
    name = "Vision Description Quality Scorer"

    def score(self, scenario, candidate, candidate_result, context):
        # type: (Scenario, CandidateConfig, CandidateResult, RunContext) -> ScoreResult
        params = scenario.scoring.params(self.id) if scenario.scoring else {}
        manifest = _load_manifest(params, context)
        if not isinstance(manifest, dict):
            return ScoreResult(
                scorer_id=self.id,
                scorer_name=self.name,
                scoring_kind="deterministic",
                success=False,
                score=0.0,
                passed=False,
                error="No manifest configured for vision-description-quality scorer.",
                human_summary="FAIL: vision-description-quality: no manifest configured",
            )

        obj = _extract_output(candidate_result)
        if obj is None:
            return ScoreResult(
                scorer_id=self.id,
                scorer_name=self.name,
                scoring_kind="deterministic",
                success=True,
                score=0.0,
                passed=False,
                error="Could not extract a JSON object from candidate output.",
                human_summary="FAIL: vision-description-quality: no parseable JSON object",
            )

        flat_text = _normalize(" ".join(_iter_strings(obj)))
        structured = _structured_fields(obj)

        required = [x for x in manifest.get("required_mentions") or [] if isinstance(x, dict)]
        optional = [x for x in manifest.get("optional_mentions") or [] if isinstance(x, dict)]
        forbidden = [str(x) for x in manifest.get("forbidden_claims") or []]
        relationships = [x for x in manifest.get("relationship_expectations") or [] if isinstance(x, dict)]
        visible_text = [x for x in manifest.get("visible_text") or [] if isinstance(x, dict)]
        ambiguous_items = [str(x) for x in manifest.get("ambiguous_items") or []]
        distractors = [str(x) for x in manifest.get("distractor_mentions") or [] if str(x).strip()]

        required_hits = [_mention_hit(item, flat_text, structured) for item in required]
        optional_hits = [_mention_hit(item, flat_text, structured) for item in optional]
        coverage = _weighted_ratio(required_hits)
        optional_coverage = _weighted_ratio(optional_hits)

        spatial = _spatial_score(required_hits, flat_text)
        rel_hits = [_relationship_hit(rel, flat_text) for rel in relationships]
        relationship_score = _ratio(rel_hits)
        text_hits = [_text_hit(t, flat_text) for t in visible_text]
        text_score = _ratio(text_hits)

        forbidden_hits = [claim for claim in forbidden if _contains_phrase(flat_text, claim)]
        hallucination_score = 0.0 if forbidden_hits else 1.0

        concrete_count = len(structured["objects"]) + len(structured["regions"])
        specificity_score = min(1.0, concrete_count / float(params.get("target_concrete_items", 8)))
        vagueness_flags = _vagueness_flags(obj, flat_text, concrete_count)
        vagueness_penalty = min(0.35, 0.10 * len(vagueness_flags))

        uncertainty_score, uncertainty_flags = _uncertainty_score(ambiguous_items, flat_text, obj)
        utility_score = _utility_score(obj, flat_text, concrete_count)
        distractor_score, distractor_hits = _distractor_score(distractors, flat_text, params)

        base_score = (
            0.30 * coverage
            + 0.15 * specificity_score
            + 0.15 * spatial
            + 0.10 * relationship_score
            + 0.10 * text_score
            + 0.10 * hallucination_score
            + 0.05 * uncertainty_score
            + 0.05 * utility_score
        )
        distractor_weight = float(params.get("distractor_weight", 0.0 if not distractors else 0.15))
        distractor_weight = max(0.0, min(0.40, distractor_weight))
        raw_score = (1.0 - distractor_weight) * base_score + distractor_weight * distractor_score
        score = max(0.0, min(1.0, raw_score - vagueness_penalty))
        threshold = scenario.scoring.threshold(self.id, 0.70) if scenario.scoring else 0.70
        passed = score >= threshold

        failure_category = _failure_category(
            forbidden_hits,
            vagueness_flags,
            coverage,
            spatial,
            relationship_score,
            text_score,
            distractor_score,
            score,
            threshold,
        )
        hit_count = sum(1 for h in required_hits if h["matched"])
        summary_prefix = "PASS" if passed else "FAIL"
        summary = (
            f"{summary_prefix}: vision-description-quality {score:.2f}; "
            f"required {hit_count}/{len(required)}, forbidden {len(forbidden_hits)}"
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
                f"coverage={coverage:.2f}, specificity={specificity_score:.2f}, "
                f"spatial={spatial:.2f}, relationships={relationship_score:.2f}, "
                f"text={text_score:.2f}, hallucination={hallucination_score:.2f}, "
                f"uncertainty={uncertainty_score:.2f}, utility={utility_score:.2f}, "
                f"distractor_resistance={distractor_score:.2f}, "
                f"vagueness_penalty={vagueness_penalty:.2f}"
            ),
            detail={
                "failure_category": failure_category,
                "coverage": {
                    "required_hit": hit_count,
                    "required_total": len(required),
                    "weighted": round(coverage, 4),
                    "required_hits": required_hits,
                    "optional_weighted": round(optional_coverage, 4),
                    "optional_hits": optional_hits,
                },
                "specificity": {
                    "score": round(specificity_score, 4),
                    "concrete_item_count": concrete_count,
                    "target_concrete_items": params.get("target_concrete_items", 8),
                },
                "spatial": {"score": round(spatial, 4)},
                "relationships": {"score": round(relationship_score, 4), "hits": rel_hits},
                "text": {"score": round(text_score, 4), "hits": text_hits},
                "hallucination": {
                    "score": round(hallucination_score, 4),
                    "forbidden_claims_found": forbidden_hits,
                },
                "uncertainty": {
                    "score": round(uncertainty_score, 4),
                    "flags": uncertainty_flags,
                },
                "vagueness": {"penalty": round(vagueness_penalty, 4), "flags": vagueness_flags},
                "utility": {"score": round(utility_score, 4)},
                "distractor_resistance": {
                    "score": round(distractor_score, 4),
                    "hits": distractor_hits,
                    "configured_terms": distractors,
                    "weight": round(distractor_weight, 4),
                },
            },
        )


def _load_manifest(params: dict[str, Any], context: RunContext) -> dict[str, Any] | None:
    inline = params.get("gold_manifest")
    if isinstance(inline, dict):
        return inline
    path = params.get("manifest_path")
    if not isinstance(path, str) or not path.strip():
        return None
    root = context.repo_root or (os.path.dirname(context.runs_root) if context.runs_root else os.getcwd())
    abs_path = path if os.path.isabs(path) else os.path.join(root, path)
    with open(abs_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else None


def _extract_output(result: CandidateResult) -> dict[str, Any] | None:
    if isinstance(result.parsed_response, dict):
        return result.parsed_response
    if isinstance(result.output, dict):
        return result.output
    raw = result.raw_response
    return _openai.extract_json_object(raw) if isinstance(raw, str) else None


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    p = _normalize(phrase)
    return bool(p) and p in normalized_text


def _structured_fields(obj: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    objects: list[dict[str, Any]] = []
    regions: list[dict[str, Any]] = []

    raw_objects = obj.get("objects_and_entities")
    if isinstance(raw_objects, list):
        objects.extend(x for x in raw_objects if isinstance(x, dict))

    raw_regions = obj.get("salient_regions")
    if isinstance(raw_regions, list):
        regions.extend(x for x in raw_regions if isinstance(x, dict))

    # visual-inspect service-shape compatibility: observations can carry labels
    # and regions even when the richer description schema is not used directly.
    observations = obj.get("observations")
    if isinstance(observations, list):
        objects.extend(x for x in observations if isinstance(x, dict))
    criteria = obj.get("criteria_results")
    if isinstance(criteria, list):
        for item in criteria:
            if isinstance(item, dict) and isinstance(item.get("observations"), list):
                objects.extend(x for x in item["observations"] if isinstance(x, dict))

    return {"objects": objects, "regions": regions}


def _aliases(item: dict[str, Any]) -> list[str]:
    aliases = item.get("aliases")
    if isinstance(aliases, list):
        out = [str(x) for x in aliases if str(x).strip()]
    else:
        out = []
    item_id = item.get("id")
    if isinstance(item_id, str):
        out.append(item_id.replace("_", " "))
    label = item.get("label")
    if isinstance(label, str):
        out.append(label)
    # Deduplicate preserving order.
    seen: set[str] = set()
    result: list[str] = []
    for a in out:
        key = _normalize(a)
        if key and key not in seen:
            seen.add(key)
            result.append(a)
    return result


def _mention_hit(item: dict[str, Any], flat_text: str, structured: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    aliases = _aliases(item)
    matched_alias = next((alias for alias in aliases if _contains_phrase(flat_text, alias)), None)
    region = str(item.get("region") or "")
    region_hit = _contains_phrase(flat_text, region) if region else False

    # If the model used structured object rows, also accept a region/location in
    # the same object dict as a stronger spatial signal.
    object_region_hit = False
    if matched_alias and region:
        for obj in structured["objects"]:
            labelish = " ".join(str(obj.get(k) or "") for k in ("label", "description"))
            locish = " ".join(str(obj.get(k) or "") for k in ("location", "region"))
            if any(_contains_phrase(_normalize(labelish), alias) for alias in aliases):
                object_region_hit = _contains_phrase(_normalize(locish), region)
                if object_region_hit:
                    break

    return {
        "id": item.get("id"),
        "matched": matched_alias is not None,
        "matched_alias": matched_alias,
        "region": region or None,
        "region_matched": bool(region_hit or object_region_hit),
        "importance": float(item.get("importance") or 1.0),
    }


def _weighted_ratio(hits: list[dict[str, Any]]) -> float:
    if not hits:
        return 1.0
    total = sum(float(h.get("importance") or 1.0) for h in hits)
    if total <= 0:
        return 1.0
    got = sum(float(h.get("importance") or 1.0) for h in hits if h.get("matched"))
    return got / total


def _ratio(flags: list[bool]) -> float:
    if not flags:
        return 1.0
    return sum(1 for x in flags if x) / float(len(flags))


def _spatial_score(required_hits: list[dict[str, Any]], flat_text: str) -> float:
    spatial_items = [h for h in required_hits if h.get("region")]
    if not spatial_items:
        return 1.0
    matched = [h for h in spatial_items if h.get("matched")]
    if not matched:
        return 0.0
    return sum(1 for h in matched if h.get("region_matched")) / float(len(spatial_items))


def _relationship_hit(rel: dict[str, Any], flat_text: str) -> bool:
    subject = str(rel.get("subject") or "").replace("_", " ")
    obj = str(rel.get("object") or "").replace("_", " ")
    relation = str(rel.get("relation") or "")
    subject_hit = not subject or _contains_phrase(flat_text, subject)
    object_hit = not obj or _contains_phrase(flat_text, obj)
    relation_hit = not relation or _contains_phrase(flat_text, relation)
    return subject_hit and object_hit and relation_hit


def _text_hit(item: dict[str, Any], flat_text: str) -> bool:
    text = str(item.get("text") or "")
    if _contains_phrase(flat_text, text):
        return True
    if not item.get("strict"):
        tokens = _WORD_RE.findall(text.lower())
        return bool(tokens) and all(tok in flat_text for tok in tokens)
    return False


def _vagueness_flags(obj: dict[str, Any], flat_text: str, concrete_count: int) -> list[str]:
    flags: list[str] = []
    answer_text = " ".join(str(obj.get(k) or "") for k in ("answer", "scene_summary"))
    if len(_WORD_RE.findall(answer_text.lower())) < 18:
        flags.append("too_short")
    if concrete_count < 3:
        flags.append("few_structured_items")
    generic_hits = [p for p in _GENERIC_PHRASES if _contains_phrase(flat_text, p)]
    if generic_hits and concrete_count < 6:
        flags.append("generic_phrasing_without_detail")
    return flags


def _uncertainty_score(ambiguous_items: list[str], flat_text: str, obj: dict[str, Any]) -> tuple[float, list[str]]:
    if not ambiguous_items:
        return 1.0, []
    uncertainties_text = _normalize(" ".join(str(x) for x in obj.get("uncertainties") or []))
    all_uncertainty_text = flat_text + " " + uncertainties_text
    uncertainty_marker = any(word in all_uncertainty_text for word in _UNCERTAINTY_WORDS)
    mentioned_ambiguous = [item for item in ambiguous_items if _contains_phrase(flat_text, item)]
    if uncertainty_marker:
        return 1.0, []
    if mentioned_ambiguous:
        return 0.25, ["ambiguous_items_mentioned_without_uncertainty"]
    return 0.6, ["no_uncertainty_for_ambiguous_fixture"]


def _utility_score(obj: dict[str, Any], flat_text: str, concrete_count: int) -> float:
    score = 0.0
    if concrete_count >= 5:
        score += 0.35
    if obj.get("salient_regions") or any(r in flat_text for r in ("upper", "lower", "center", "left", "right")):
        score += 0.25
    if obj.get("relationships"):
        score += 0.20
    if obj.get("answer") or obj.get("scene_summary"):
        score += 0.20
    return min(1.0, score)


def _distractor_score(distractors: list[str], flat_text: str, params: dict[str, Any]) -> tuple[float, list[str]]:
    """Score whether a response stayed focused instead of inventorying known decoys.

    Some visual-inspect scenarios intentionally place a noisy center scene behind
    crisp border UI. In those cases, mentioning one decoy in passing is tolerable,
    but spending attention on several decoys is the failure mode we want surfaced.
    """
    if not distractors:
        return 1.0, []
    hits = [d for d in distractors if _contains_phrase(flat_text, d)]
    allowed = int(params.get("allowed_distractor_mentions", 1))
    allowed = max(0, allowed)
    excess = max(0, len(hits) - allowed)
    # Default curve: one excess hit => 0.75, two => 0.50, four+ => 0.0.
    score = max(0.0, 1.0 - 0.25 * excess)
    return score, hits


def _failure_category(
    forbidden_hits: list[str],
    vagueness_flags: list[str],
    coverage: float,
    spatial: float,
    relationship: float,
    text: float,
    distractor: float,
    score: float,
    threshold: float,
) -> str | None:
    if score >= threshold:
        return None
    if forbidden_hits:
        return "hallucinated_forbidden_claim"
    if vagueness_flags and coverage < 0.45:
        return "vague_summary"
    if coverage < 0.45:
        return "missed_salient_objects"
    if spatial < 0.45:
        return "poor_spatial_grounding"
    if relationship < 0.5:
        return "missed_relationships"
    if text < 0.5:
        return "missed_visible_text"
    if distractor < 0.5:
        return "distracted_by_visual_noise"
    return "low_description_quality"
