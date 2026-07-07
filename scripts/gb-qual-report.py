#!/usr/bin/env python3
"""gb-qual-report — qualitative model comparison with optional LLM judging.

This tool complements ``gb-report`` for prose-heavy suites where pass/fail scores
are intentionally thin. It reads completed GoblinBench cells from the canonical
SQLite store, assembles model outputs side-by-side, optionally asks a separate
judge model for a comparative ranking, and writes a durable Markdown artifact.

The workflow is deliberately repeatable:

* judge prompt template is file-backed and copied into every campaign artifact;
* every per-scenario judge request is written before the model call;
* raw and parsed judge responses are saved separately;
* ``--dry-run`` lets you iterate on prompt/rubric shape without spending model
  calls;
* ``--judge-response-dir`` can re-render a report from saved/manual responses.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gb.models import CandidateConfig, CandidateKind  # noqa: E402
from gb.runners import _openai  # noqa: E402
from gb.store import DbPaths, open_db  # noqa: E402

DEFAULT_RUBRIC = """Rank the outputs by qualitative usefulness for the scenario.
Prefer answers that are specific, complete, well-structured, grounded in the
provided task, and easy for a human to use. Penalize vague prose, invented facts,
missed requirements, unnecessary caveats, unsafe overreach, and poor organization.
Use the numeric score only as a rough within-scenario signal; the commentary is
more important than tiny score differences.
"""

DEFAULT_TEMPLATE = """You are a careful qualitative benchmark judge for GoblinBench.

Your job is to compare several model outputs for one scenario. The candidate
labels may be anonymized; do not infer model identity from style. Judge only the
provided outputs against the scenario and rubric.

Scenario: {{scenario_id}}
Scenario name: {{scenario_name}}

Scenario prompt / context:
{{scenario_prompt}}

Rubric:
{{rubric}}

Candidate outputs:
{{outputs_markdown}}

Return ONLY a JSON object with this shape:
{
  "scenario_id": "{{scenario_id}}",
  "overall_commentary": "2-5 sentences comparing the field",
  "rankings": [
    {
      "label": "A",
      "rank": 1,
      "score": 8.5,
      "summary": "one-sentence verdict",
      "strengths": ["short bullet", "short bullet"],
      "weaknesses": ["short bullet"]
    }
  ],
  "caveats": ["uncertainty or judging limitation, if any"]
}

Rules:
- Include every candidate label exactly once in rankings.
- Rank 1 is best. Scores are 0-10 and may tie only if truly indistinguishable.
- Be concrete: mention the observable differences that drove ranking.
- Do not add markdown fences or prose outside the JSON object.
"""

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_name(value: str) -> str:
    return _SAFE_NAME_RE.sub("-", value).strip("-.") or "scenario"


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [piece.strip() for piece in value.split(",") if piece.strip()]


def read_text_arg(text_value: str | None, file_value: str | None, default: str) -> str:
    if file_value:
        return Path(file_value).read_text(encoding="utf-8")
    if text_value is not None:
        return text_value
    return default


def load_candidates(path: Path) -> dict[str, CandidateConfig]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("id")): CandidateConfig.from_dict(item) for item in raw if item.get("id")}


def build_filters(args: argparse.Namespace) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    runs = parse_csv(args.runs)
    if runs:
        where.append(f"cr.run_id IN ({','.join('?' for _ in runs)})")
        params.extend(runs)
    if args.suite:
        where.append("cr.suite = ?")
        params.append(args.suite)
    if args.scenario:
        where.append("cr.scenario_id = ?")
        params.append(args.scenario)
    models = parse_csv(args.model)
    if models:
        clauses = []
        for model in models:
            clauses.append("(cr.model = ? OR cr.candidate_id = ?)")
            params.extend([model, model])
        where.append("(" + " OR ".join(clauses) + ")")
    if args.provider:
        where.append("cr.provider = ?")
        params.append(args.provider)
    if args.success_only:
        where.append("cr.success = 1")
    return (" WHERE " + " AND ".join(where)) if where else "", params


def fetch_cells(conn: Any, args: argparse.Namespace) -> list[dict[str, Any]]:
    where_sql, params = build_filters(args)
    sql = f"""
        SELECT cr.id, cr.run_id, cr.scenario_id, cr.scenario_version, cr.suite, cr.scenario_name,
               cr.candidate_id, cr.candidate_name, cr.candidate_kind, cr.model, cr.provider,
               cr.base_url, cr.display_name, cr.success, cr.error, cr.duration_ms,
               cr.artifact_directory, cr.primary_scorer_id, cr.primary_score, cr.primary_passed,
               cr.primary_summary, cr.primary_explanation, cr.failure_categories_json,
               r.started_at, r.label AS run_label
        FROM candidate_results cr
        JOIN runs r ON r.run_id = cr.run_id
        {where_sql}
        ORDER BY cr.scenario_id, cr.run_id DESC, cr.model, cr.candidate_id
        LIMIT ?
    """
    params.append(args.limit)
    return [dict(row) for row in conn.execute(sql, params)]


def fetch_artifact_text(conn: Any, repo_root: Path, candidate_result_id: int, name: str) -> str | None:
    row = conn.execute(
        "SELECT content_bytes, external_path FROM artifacts WHERE candidate_result_id=? AND name=?",
        (candidate_result_id, name),
    ).fetchone()
    if row is None:
        return None
    if row["content_bytes"] is not None:
        return row["content_bytes"].decode("utf-8", errors="replace")
    if row["external_path"]:
        path = repo_root / row["external_path"]
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return None


def load_scenario_prompt(repo_root: Path, suite: str | None, scenario_id: str) -> str:
    if not suite:
        return ""
    scenario_name = scenario_id.split(".", 1)[1] if "." in scenario_id else scenario_id
    path = repo_root / "suites" / suite / f"{scenario_name}.json"
    if not path.exists():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    scenario_input = raw.get("input") or {}
    prompt = scenario_input.get("prompt")
    if isinstance(prompt, str):
        return prompt
    return raw.get("description") or ""


def truncate_text(text: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(text) <= limit:
        return text, False
    return text[:limit] + f"\n\n[truncated: {len(text) - limit:,} chars omitted]", True


def label_for(index: int) -> str:
    # A..Z, AA..AZ if a very large comparison sneaks in.
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < len(alphabet):
        return alphabet[index]
    return alphabet[(index // len(alphabet)) - 1] + alphabet[index % len(alphabet)]


def make_output_records(
    conn: Any,
    repo_root: Path,
    cells: list[dict[str, Any]],
    *,
    blind: bool,
    max_output_chars: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, cell in enumerate(cells):
        label = label_for(idx) if blind else (cell.get("model") or cell.get("candidate_id") or label_for(idx))
        output = fetch_artifact_text(conn, repo_root, int(cell["id"]), "output.json")
        if output is None:
            output = cell.get("primary_summary") or cell.get("error") or "(no output artifact stored)"
        truncated_output, truncated = truncate_text(output, max_output_chars)
        records.append({
            "label": label,
            "candidate_id": cell.get("candidate_id"),
            "candidate_name": cell.get("candidate_name"),
            "model": cell.get("model"),
            "provider": cell.get("provider"),
            "run_id": cell.get("run_id"),
            "success": bool(cell.get("success")),
            "error": cell.get("error"),
            "duration_ms": cell.get("duration_ms"),
            "output": truncated_output,
            "output_chars": len(output),
            "truncated": truncated,
            "artifact_directory": cell.get("artifact_directory"),
        })
    return records


def outputs_markdown(records: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for record in records:
        status = "success" if record["success"] else f"error: {record.get('error') or 'unknown'}"
        meta = f"label={record['label']} status={status} duration_ms={record.get('duration_ms')}"
        blocks.append(f"### Candidate {record['label']}\n\nMetadata: `{meta}`\n\n```text\n{record['output']}\n```")
    return "\n\n".join(blocks)


def render_template(
    template: str,
    *,
    scenario_id: str,
    scenario_name: str,
    scenario_prompt: str,
    rubric: str,
    records: list[dict[str, Any]],
) -> str:
    replacements = {
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "scenario_prompt": scenario_prompt or "(scenario prompt unavailable in store; judge the outputs and metadata only)",
        "rubric": rubric,
        "outputs_markdown": outputs_markdown(records),
        "outputs_json": json.dumps(records, ensure_ascii=False, indent=2),
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def extract_judge_json(text: str) -> dict[str, Any] | None:
    parsed = _openai.extract_json_object(text)
    if isinstance(parsed, dict):
        return parsed
    return None


def normalize_judgement(parsed: dict[str, Any] | None, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    valid_labels = {str(r["label"]) for r in records}
    rankings = parsed.get("rankings")
    if not isinstance(rankings, list):
        return parsed
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rankings:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if label not in valid_labels or label in seen:
            continue
        seen.add(label)
        out = dict(item)
        out["label"] = label
        rank_value = out.get("rank")
        try:
            out["rank"] = int(rank_value) if rank_value is not None else len(normalized) + 1
        except (TypeError, ValueError):
            out["rank"] = len(normalized) + 1
        score_value = out.get("score")
        try:
            out["score"] = float(score_value) if score_value is not None else None
        except (TypeError, ValueError):
            out["score"] = None
        normalized.append(out)
    # Preserve parse even if incomplete, but mark missing labels in caveats.
    missing = sorted(valid_labels - seen)
    if missing:
        caveats_value = parsed.get("caveats")
        caveats = caveats_value if isinstance(caveats_value, list) else []
        parsed["caveats"] = [*caveats, f"Judge response omitted label(s): {', '.join(missing)}"]
    parsed["rankings"] = sorted(normalized, key=lambda r: (r.get("rank") if r.get("rank") is not None else 999, str(r.get("label"))))
    return parsed


def candidate_from_args(args: argparse.Namespace, candidates: dict[str, CandidateConfig]) -> CandidateConfig | None:
    if args.judge_candidate:
        cand = candidates.get(args.judge_candidate)
        if cand is None:
            raise SystemExit(f"Error: --judge-candidate {args.judge_candidate!r} not found in candidates file.")
        return cand
    if args.judge_model:
        return CandidateConfig(
            id=f"judge-{args.judge_provider or 'openai'}-{args.judge_model}",
            name=f"Judge {args.judge_provider or 'openai'} {args.judge_model}",
            kind=CandidateKind.OpenAiModel,
            model=args.judge_model,
            provider=args.judge_provider or "openai",
            base_url=args.judge_base_url or ("http://127.0.0.1:18082/v1" if args.judge_provider == "den-router" else None),
            api_key_env=args.judge_api_key_env,
            system_prompt=args.judge_system,
            config={
                "temperature": args.judge_temperature,
                "max_tokens": args.judge_max_tokens,
            },
        )
    return None


def judge_display(candidate: CandidateConfig | None) -> str:
    if candidate is None:
        return "none"
    provider = candidate.provider or "openai"
    model = candidate.model or "unknown"
    return f"{provider}/{model}"


def build_request_body(args: argparse.Namespace, candidate: CandidateConfig, prompt: str) -> dict[str, Any]:
    system = args.judge_system or candidate.system_prompt or "You are a careful benchmark judge. Return valid JSON only."
    body: dict[str, Any] = {
        "model": candidate.model or args.judge_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": args.judge_temperature,
        "max_tokens": args.judge_max_tokens,
    }
    if not args.no_json_response_format:
        body["response_format"] = {"type": "json_object"}
    if args.judge_extra_json:
        try:
            extra = json.loads(args.judge_extra_json)
        except json.JSONDecodeError as ex:
            raise SystemExit(f"Error: --judge-extra-json is not valid JSON: {ex}") from ex
        if not isinstance(extra, dict):
            raise SystemExit("Error: --judge-extra-json must be a JSON object.")
        body.update(extra)
    return body


def call_judge(args: argparse.Namespace, candidate: CandidateConfig, request_body: dict[str, Any]) -> tuple[str, str | None]:
    base_url = candidate.base_url or candidate.endpoint or args.judge_base_url or "https://api.openai.com/v1"
    api_key = _openai.resolve_api_key(candidate)
    resp = _openai.post_chat_completions(base_url, request_body, api_key, timeout=args.judge_timeout)
    if resp.error:
        return "", resp.error
    if not resp.success:
        return resp.body or "", f"HTTP {resp.status_code}: {(resp.body or '')[:500]}"
    try:
        doc = json.loads(resp.body)
        content = _openai.extract_message_content(_openai.extract_message(doc)) or ""
        return content, None
    except Exception as ex:  # noqa: BLE001
        return resp.body or "", f"failed to parse judge envelope: {ex}"


def load_response_from_dir(response_dir: Path, scenario_id: str) -> str | None:
    base = safe_name(scenario_id)
    for suffix in (".raw.txt", ".txt", ".json"):
        path = response_dir / f"{base}{suffix}"
        if path.exists():
            return path.read_text(encoding="utf-8")
    return None


def format_list(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(x) for x in value if str(x).strip())
    if value is None:
        return ""
    return str(value)


def md_escape_table(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def render_report(
    *,
    args: argparse.Namespace,
    campaign_id: str,
    cells_by_scenario: dict[str, list[dict[str, Any]]],
    records_by_scenario: dict[str, list[dict[str, Any]]],
    judgements: dict[str, dict[str, Any] | None],
    errors: dict[str, str],
    judge_name: str,
    template: str,
    rubric: str,
) -> str:
    lines: list[str] = [
        f"# GoblinBench Qualitative Comparison — {campaign_id}",
        "",
        f"Generated: `{dt.datetime.now(dt.timezone.utc).isoformat()}`",
        f"Judge: `{judge_name}`",
        f"Judge prompt SHA256: `{hashlib.sha256(template.encode('utf-8')).hexdigest()}`",
        f"Rubric SHA256: `{hashlib.sha256(rubric.encode('utf-8')).hexdigest()}`",
        "",
        "## Scope",
        "",
        f"- runs: `{args.runs or 'latest/filter-selected'}`",
        f"- suite: `{args.suite or '*'}`",
        f"- scenario: `{args.scenario or '*'}`",
        f"- model/candidate filter: `{args.model or '*'}`",
        f"- blind judge labels: `{not args.no_blind}`",
        f"- max output chars per candidate sent to judge: `{args.max_output_chars}`",
        "",
        "## Scenario summary",
        "",
        "| scenario | candidates | judged | top label | top model | top score | notes |",
        "|---|---:|---|---|---|---:|---|",
    ]
    for scenario_id in sorted(records_by_scenario):
        records = records_by_scenario[scenario_id]
        judgement = judgements.get(scenario_id)
        error = errors.get(scenario_id)
        top = None
        if judgement and isinstance(judgement.get("rankings"), list) and judgement["rankings"]:
            top = judgement["rankings"][0]
        top_label = top.get("label") if isinstance(top, dict) else ""
        by_label = {str(r["label"]): r for r in records}
        top_record = by_label.get(str(top_label)) if top_label else None
        top_model = (top_record or {}).get("model") or (top_record or {}).get("candidate_id") or ""
        top_score = top.get("score") if isinstance(top, dict) else None
        score_text = f"{float(top_score):.1f}" if isinstance(top_score, (int, float)) else ""
        judged = "yes" if judgement else ("error" if error else "not run")
        note = error or (judgement.get("overall_commentary") if judgement else "") or ""
        lines.append(
            f"| `{md_escape_table(scenario_id)}` | {len(records)} | {judged} | {md_escape_table(top_label)} | "
            f"{md_escape_table(top_model)} | {score_text} | {md_escape_table(note[:240])} |"
        )

    for scenario_id in sorted(records_by_scenario):
        records = records_by_scenario[scenario_id]
        judgement = judgements.get(scenario_id)
        error = errors.get(scenario_id)
        lines.extend(["", f"## {scenario_id}", ""])
        if error:
            lines.extend([f"> Judge error: `{error}`", ""])
        if judgement:
            commentary = judgement.get("overall_commentary") or ""
            if commentary:
                lines.extend([str(commentary), ""])
            lines.extend([
                "### Judge ranking",
                "",
                "| rank | label | model | score | summary | strengths | weaknesses |",
                "|---:|---|---|---:|---|---|---|",
            ])
            by_label = {str(r["label"]): r for r in records}
            for item in judgement.get("rankings") or []:
                if not isinstance(item, dict):
                    continue
                rec = by_label.get(str(item.get("label")), {})
                model = rec.get("model") or rec.get("candidate_id") or ""
                score = item.get("score")
                score_text = f"{float(score):.1f}" if isinstance(score, (int, float)) else ""
                lines.append(
                    f"| {md_escape_table(item.get('rank'))} | {md_escape_table(item.get('label'))} | "
                    f"{md_escape_table(model)} | {score_text} | {md_escape_table(item.get('summary'))} | "
                    f"{md_escape_table(format_list(item.get('strengths')))} | {md_escape_table(format_list(item.get('weaknesses')))} |"
                )
            caveats = judgement.get("caveats")
            if caveats:
                lines.extend(["", "Caveats:"])
                for caveat in caveats if isinstance(caveats, list) else [caveats]:
                    lines.append(f"- {caveat}")
                lines.append("")
        else:
            lines.extend(["No parsed judge ranking for this scenario.", ""])

        lines.extend([
            "### Candidate outputs",
            "",
            "| label | model | provider | run | status | chars | artifact | excerpt |",
            "|---|---|---|---|---|---:|---|---|",
        ])
        for rec in records:
            status = "success" if rec["success"] else f"error: {rec.get('error') or 'unknown'}"
            excerpt, _ = truncate_text(rec["output"].replace("\n", " "), 260)
            artifact = rec.get("artifact_directory") or ""
            lines.append(
                f"| {md_escape_table(rec['label'])} | {md_escape_table(rec.get('model') or rec.get('candidate_id'))} | "
                f"{md_escape_table(rec.get('provider'))} | `{md_escape_table(rec.get('run_id'))}` | {md_escape_table(status)} | "
                f"{rec.get('output_chars') or 0} | `{md_escape_table(artifact)}` | {md_escape_table(excerpt)} |"
            )
    lines.extend([
        "",
        "---",
        "",
        "Generated by `gb-qual-report.py`. Judge rankings are qualitative model output, not ground truth; inspect raw candidate and judge artifacts before making high-stakes conclusions.",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gb-qual-report",
        description="Build a Markdown qualitative comparison report from GoblinBench runs, optionally judged by an LLM.",
    )
    parser.add_argument("--runs", help="comma-separated run_id list")
    parser.add_argument("--suite", default="qualitative", help="suite filter (default qualitative)")
    parser.add_argument("--scenario", help="single scenario id")
    parser.add_argument("--model", help="comma-separated model or candidate_id filters")
    parser.add_argument("--provider")
    parser.add_argument("--success-only", action="store_true", help="exclude runner-error cells from judge packets")
    parser.add_argument("--limit", type=int, default=500, help="max cells to read (default 500)")

    parser.add_argument("--campaign", help="stable campaign id; default qual-<UTC timestamp>")
    parser.add_argument("--out", help="Markdown report path; default runs/qualitative/<campaign>/qualitative-report.md")
    parser.add_argument("--out-dir", help="artifact directory; default derived from --out/--campaign")
    parser.add_argument("--dry-run", action="store_true", help="write judge prompts/report skeleton but do not call judge")
    parser.add_argument("--no-judge", action="store_true", help="do not call a judge; produce side-by-side report only")
    parser.add_argument("--judge-response-dir", help="read saved/manual judge responses from this directory instead of calling judge")

    parser.add_argument("--rubric", help="rubric text literal")
    parser.add_argument("--rubric-file", help="path to rubric markdown/text")
    parser.add_argument("--judge-template", help="path to prompt template; supports {{scenario_id}}, {{scenario_name}}, {{scenario_prompt}}, {{rubric}}, {{outputs_markdown}}, {{outputs_json}}")
    parser.add_argument("--max-output-chars", type=int, default=12000, help="per-candidate output char budget sent to judge (default 12000)")
    parser.add_argument("--no-blind", action="store_true", help="send real model ids as judge labels instead of anonymized A/B/C labels")

    parser.add_argument("--candidates", help="candidates.json path for --judge-candidate (default repo candidates.json)")
    parser.add_argument("--judge-candidate", help="candidate id from candidates.json to use as judge")
    parser.add_argument("--judge-model", help="OpenAI-compatible judge model id")
    parser.add_argument("--judge-provider", help="judge provider label; den-router defaults base_url to local router")
    parser.add_argument("--judge-base-url", help="OpenAI-compatible base URL for judge")
    parser.add_argument("--judge-api-key-env", help="env var containing judge API key")
    parser.add_argument("--judge-system", help="judge system prompt override")
    parser.add_argument("--judge-temperature", type=float, default=0.0)
    parser.add_argument("--judge-max-tokens", type=int, default=4096)
    parser.add_argument("--judge-timeout", type=float, default=300.0)
    parser.add_argument("--judge-extra-json", help="JSON object merged into the judge chat/completions request for provider-specific knobs")
    parser.add_argument("--no-json-response-format", action="store_true", help="omit response_format=json_object for judge endpoints that reject it")
    args = parser.parse_args(argv)

    paths = DbPaths.resolve()
    if not paths.db_path.exists():
        print(f"Error: store DB not found at {paths.db_path}. Run a benchmark first.", file=sys.stderr)
        return 1

    campaign_id = args.campaign or f"qual-{utc_stamp()}"
    out_path = Path(args.out) if args.out else paths.runs_root / "qualitative" / campaign_id / "qualitative-report.md"
    out_dir = Path(args.out_dir) if args.out_dir else out_path.parent
    request_dir = out_dir / "judge-requests"
    response_dir = out_dir / "judge-responses"
    request_dir.mkdir(parents=True, exist_ok=True)
    response_dir.mkdir(parents=True, exist_ok=True)

    rubric = read_text_arg(args.rubric, args.rubric_file, DEFAULT_RUBRIC)
    default_template_path = paths.repo_root / "templates" / "qualitative-judge-v1.md"
    if args.judge_template:
        template = Path(args.judge_template).read_text(encoding="utf-8")
    elif default_template_path.exists():
        template = default_template_path.read_text(encoding="utf-8")
    else:
        template = DEFAULT_TEMPLATE
    (out_dir / "judge-template.md").write_text(template, encoding="utf-8")
    (out_dir / "rubric.md").write_text(rubric, encoding="utf-8")

    candidates_path = Path(args.candidates) if args.candidates else paths.repo_root / "candidates.json"
    candidates = load_candidates(candidates_path)
    judge_candidate = candidate_from_args(args, candidates)
    if not (args.dry_run or args.no_judge or args.judge_response_dir) and judge_candidate is None:
        print("Error: choose --judge-candidate or --judge-model, or pass --dry-run/--no-judge/--judge-response-dir.", file=sys.stderr)
        return 2

    conn = open_db(paths.db_path)
    try:
        cells = fetch_cells(conn, args)
        if not cells:
            print("No cells matched the filters.", file=sys.stderr)
            return 1
        cells_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for cell in cells:
            cells_by_scenario.setdefault(str(cell["scenario_id"]), []).append(cell)

        records_by_scenario: dict[str, list[dict[str, Any]]] = {}
        judgements: dict[str, dict[str, Any] | None] = {}
        errors: dict[str, str] = {}
        all_judgement_records: dict[str, Any] = {}
        response_source_dir = Path(args.judge_response_dir) if args.judge_response_dir else None

        for scenario_id, scenario_cells in cells_by_scenario.items():
            scenario_name = scenario_cells[0].get("scenario_name") or scenario_id
            suite = scenario_cells[0].get("suite")
            scenario_prompt = load_scenario_prompt(paths.repo_root, suite, scenario_id)
            records = make_output_records(
                conn,
                paths.repo_root,
                scenario_cells,
                blind=not args.no_blind,
                max_output_chars=args.max_output_chars,
            )
            records_by_scenario[scenario_id] = records
            prompt = render_template(
                template,
                scenario_id=scenario_id,
                scenario_name=scenario_name,
                scenario_prompt=scenario_prompt,
                rubric=rubric,
                records=records,
            )
            stem = safe_name(scenario_id)
            (request_dir / f"{stem}.md").write_text(prompt, encoding="utf-8")

            request_body = None
            if judge_candidate is not None:
                request_body = build_request_body(args, judge_candidate, prompt)
                (request_dir / f"{stem}.json").write_text(json.dumps(request_body, indent=2, ensure_ascii=False), encoding="utf-8")

            raw_response: str | None = None
            judge_error: str | None = None
            if response_source_dir is not None:
                raw_response = load_response_from_dir(response_source_dir, scenario_id)
                if raw_response is None:
                    judge_error = f"no saved response found for {scenario_id} in {response_source_dir}"
            elif not (args.dry_run or args.no_judge):
                assert judge_candidate is not None and request_body is not None
                raw_response, judge_error = call_judge(args, judge_candidate, request_body)

            if raw_response is not None:
                (response_dir / f"{stem}.raw.txt").write_text(raw_response, encoding="utf-8")
                parsed = normalize_judgement(extract_judge_json(raw_response), records)
                judgements[scenario_id] = parsed
                if parsed is not None:
                    (response_dir / f"{stem}.parsed.json").write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
                else:
                    errors[scenario_id] = judge_error or "judge response did not contain parseable JSON object"
            else:
                judgements[scenario_id] = None
            if judge_error:
                errors[scenario_id] = judge_error
                (response_dir / f"{stem}.error.txt").write_text(judge_error, encoding="utf-8")

            all_judgement_records[scenario_id] = {
                "records": records,
                "judgement": judgements.get(scenario_id),
                "error": errors.get(scenario_id),
            }
    finally:
        conn.close()

    (out_dir / "judgements.json").write_text(json.dumps(all_judgement_records, indent=2, ensure_ascii=False), encoding="utf-8")
    report = render_report(
        args=args,
        campaign_id=campaign_id,
        cells_by_scenario=cells_by_scenario,
        records_by_scenario=records_by_scenario,
        judgements=judgements,
        errors=errors,
        judge_name=judge_display(judge_candidate) if not (args.no_judge or args.dry_run) else "not run",
        template=template,
        rubric=rubric,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Wrote {out_path} ({len(report):,} bytes, {len(cells)} cell(s), {len(records_by_scenario)} scenario(s))")
    print(f"Artifacts: {out_dir}")
    if args.dry_run:
        print("Dry run: judge prompts were written but no judge calls were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
