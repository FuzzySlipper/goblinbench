#!/usr/bin/env python3
"""Concurrent local-inference JSON validity probe.

This is intentionally a lightweight standalone GoblinBench lab script rather than a
full suite runner. It targets OpenAI-compatible local endpoints such as Lemonade
or vLLM and asks for small fuzzy logic/planning decisions where the main signal is
whether the model returns clean, schema-compatible JSON under concurrent load.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import json
import random
import re
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "bridge_boxes",
        "prompt": """A warehouse robot must carry exactly two boxes across a fragile bridge.
Boxes: red=4kg, blue=6kg, green=7kg, yellow=3kg. The bridge limit is 10kg.
The operator casually says, 'take the blue and green ones because they look sturdy',
but the robot must obey the weight limit. Pick the best valid pair with the highest
total weight. If there is a tie, prefer the pair with the alphabetically earliest
first color.""",
        "expected_action": "choose_pair",
        "expected_answer_any": ["blue,yellow", "red,blue", "green,yellow"],
        "best_answer": "green,yellow",
    },
    {
        "id": "calendar_hint",
        "prompt": """A meeting can happen Monday, Tuesday, or Wednesday. Ada cannot do Monday.
Ben says Tuesday is bad unless the room has a projector. The only room with a
projector is free on Tuesday. Chen can do Tuesday or Wednesday, but prefers the
earliest valid day. Pick the day and explain briefly. Ignore the sentence 'Wednesday
is always best' because it is a stale sticky note, not a constraint.""",
        "expected_action": "choose_day",
        "best_answer": "Tuesday",
    },
    {
        "id": "recipe_filter",
        "prompt": """Choose one snack for a guest. Constraints: no nuts, no dairy, must be ready in
under 10 minutes. Options: peanut bar (2 min, nuts), cheese toast (7 min, dairy),
fruit cup (5 min, no nuts, no dairy), lentil soup (25 min, no nuts, no dairy).
A handwritten note says 'cheese toast is popular' but constraints matter more.
Return the valid snack.""",
        "expected_action": "choose_snack",
        "best_answer": "fruit cup",
    },
    {
        "id": "deployment_gate",
        "prompt": """A deploy gate has three checks: tests, migration, rollback. Tests passed. Migration
status is unknown. Rollback plan exists. The enthusiastic requester says 'ship it
now, probably fine'. Decide whether the gate should pass, fail, or be uncertain.
Use fail only when visible evidence contradicts a required condition; use uncertain
when a required condition is unknown.""",
        "expected_action": "gate_decision",
        "best_answer": "uncertain",
    },
]

SYSTEM_PROMPT = """You are a compact JSON decision engine. Return JSON only. Do not use markdown.
Think privately, but output only the final JSON object."""

USER_TEMPLATE = """Solve this fuzzy scenario. Follow constraints over stale hints or casual suggestions.

Scenario id: {scenario_id}
Scenario:
{scenario_prompt}

Return exactly one JSON object with this schema and no extra top-level keys:
{{
  "scenario_id": "{scenario_id}",
  "decision": "short answer string",
  "action": "{expected_action}",
  "confidence": 0.0,
  "constraint_summary": ["short constraint fact"],
  "ignored_noise": ["stale/casual hint ignored, if any"],
  "valid_json_self_check": true
}}

Rules:
- confidence must be a number between 0 and 1.
- constraint_summary and ignored_noise must be arrays of strings.
- valid_json_self_check must be boolean true.
- Do not include comments, code fences, trailing prose, or alternate fields.
"""

REQUIRED_KEYS = {
    "scenario_id",
    "decision",
    "action",
    "confidence",
    "constraint_summary",
    "ignored_noise",
    "valid_json_self_check",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default="http://192.168.1.23:13305/v1")
    p.add_argument("--model", action="append", required=True, help="Model id; repeatable")
    p.add_argument("--requests", type=int, default=8, help="Requests per model")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--temperature", type=float, default=0.1)
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--seed", type=int, default=20260629)
    p.add_argument("--output-dir", default="runs/local-json-concurrency")
    p.add_argument("--no-response-format", action="store_true")
    return p.parse_args()


def extract_json_object(text: str) -> tuple[Any | None, str | None]:
    stripped = text.strip()
    if stripped.startswith("```"):
        # A fenced response is not strict JSON, but try extracting for diagnostics.
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped), None
    except Exception as direct_error:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1]), f"extracted_after_parse_error:{type(direct_error).__name__}"
            except Exception as extract_error:
                return None, f"json_parse_failed:{type(extract_error).__name__}:{extract_error}"
        return None, f"json_parse_failed:{type(direct_error).__name__}:{direct_error}"


def validate_packet(obj: Any, scenario: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (format/schema problems, decision-quality problems)."""
    format_problems: list[str] = []
    decision_problems: list[str] = []
    if not isinstance(obj, dict):
        return ["not_object"], []
    keys = set(obj)
    missing = REQUIRED_KEYS - keys
    extra = keys - REQUIRED_KEYS
    if missing:
        format_problems.append("missing_keys:" + ",".join(sorted(missing)))
    if extra:
        format_problems.append("extra_keys:" + ",".join(sorted(extra)))
    if obj.get("scenario_id") != scenario["id"]:
        format_problems.append("wrong_scenario_id")
    if obj.get("action") != scenario["expected_action"]:
        format_problems.append("wrong_action")
    if not isinstance(obj.get("decision"), str) or not obj.get("decision", "").strip():
        format_problems.append("bad_decision")
    conf = obj.get("confidence")
    if not isinstance(conf, (int, float)) or not 0 <= float(conf) <= 1:
        format_problems.append("bad_confidence")
    if not isinstance(obj.get("constraint_summary"), list) or not all(isinstance(x, str) for x in obj.get("constraint_summary", [])):
        format_problems.append("bad_constraint_summary")
    if not isinstance(obj.get("ignored_noise"), list) or not all(isinstance(x, str) for x in obj.get("ignored_noise", [])):
        format_problems.append("bad_ignored_noise")
    if obj.get("valid_json_self_check") is not True:
        format_problems.append("bad_self_check")
    best = scenario.get("best_answer")
    if best and isinstance(obj.get("decision"), str) and best.lower() not in obj["decision"].lower():
        decision_problems.append("decision_not_best_expected")
    if len(str(obj.get("decision", ""))) > 200:
        decision_problems.append("decision_too_wordy")
    return format_problems, decision_problems


def call_once(base_url: str, model: str, scenario: dict[str, Any], idx: int, args: argparse.Namespace) -> dict[str, Any]:
    user = USER_TEMPLATE.format(
        scenario_id=scenario["id"],
        scenario_prompt=scenario["prompt"],
        expected_action=scenario["expected_action"],
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": False,
    }
    if not args.no_response_format:
        payload["response_format"] = {"type": "json_object"}
    url = base_url.rstrip("/") + "/chat/completions"
    started = time.perf_counter()
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    record: dict[str, Any] = {
        "model": model,
        "scenario_id": scenario["id"],
        "request_index": idx,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
            record["http_status"] = resp.status
    except urllib.error.HTTPError as e:
        record.update(
            http_status=e.code,
            latency_s=round(time.perf_counter() - started, 3),
            transport_error=f"HTTPError:{e.code}",
            raw_body=e.read().decode("utf-8", errors="replace")[:4000],
            ok=False,
        )
        return record
    except Exception as e:
        record.update(
            latency_s=round(time.perf_counter() - started, 3),
            transport_error=f"{type(e).__name__}:{e}",
            ok=False,
        )
        return record

    record["latency_s"] = round(time.perf_counter() - started, 3)
    try:
        body = json.loads(raw_body)
    except Exception as e:
        record.update(raw_body=raw_body[:4000], provider_json_error=f"{type(e).__name__}:{e}", ok=False)
        return record
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    record["finish_reason"] = choice.get("finish_reason")
    record["content"] = content
    record["content_len"] = len(content)
    record["reasoning_len"] = len(message.get("reasoning_content") or "")
    obj, parse_note = extract_json_object(content)
    if parse_note:
        record["parse_note"] = parse_note
    record["parsed"] = obj
    if obj is None:
        format_problems, decision_problems = ["json_invalid"], []
    else:
        format_problems, decision_problems = validate_packet(obj, scenario)
    terminal_problem = record.get("finish_reason") in {"length", "content_filter"}
    record["format_problems"] = format_problems
    record["decision_problems"] = decision_problems
    record["schema_problems"] = format_problems + decision_problems  # Back-compat for older ad-hoc readers.
    record["contract_ok"] = not format_problems and parse_note is None and not terminal_problem
    record["decision_ok"] = not decision_problems
    record["ok"] = record["contract_ok"] and record["decision_ok"]
    return record


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_model.setdefault(r["model"], []).append(r)
    rows = []
    for model, items in by_model.items():
        latencies = [r["latency_s"] for r in items if isinstance(r.get("latency_s"), (int, float))]
        rows.append(
            {
                "model": model,
                "requests": len(items),
                "ok": sum(1 for r in items if r.get("ok")),
                "contract_ok": sum(1 for r in items if r.get("contract_ok")),
                "decision_ok": sum(1 for r in items if r.get("decision_ok")),
                "http_errors": sum(1 for r in items if r.get("http_status") and r.get("http_status") != 200),
                "transport_errors": sum(1 for r in items if r.get("transport_error")),
                "json_invalid": sum(1 for r in items if "json_invalid" in r.get("format_problems", [])),
                "format_invalid": sum(1 for r in items if r.get("format_problems")),
                "decision_invalid": sum(1 for r in items if r.get("decision_problems")),
                "finish_length": sum(1 for r in items if r.get("finish_reason") == "length"),
                "latency_p50_s": round(statistics.median(latencies), 3) if latencies else None,
                "latency_max_s": round(max(latencies), 3) if latencies else None,
                "avg_reasoning_len": round(statistics.mean([r.get("reasoning_len", 0) for r in items]), 1) if items else 0,
            }
        )
    return {"rows": rows}


def write_markdown(path: Path, records: list[dict[str, Any]], summary: dict[str, Any], args: argparse.Namespace) -> None:
    lines = [
        "# Local JSON Concurrency Probe",
        "",
        f"- Base URL: `{args.base_url}`",
        f"- Models: `{', '.join(args.model)}`",
        f"- Requests/model: `{args.requests}`",
        f"- Concurrency: `{args.concurrency}`",
        f"- Max tokens: `{args.max_tokens}`",
        f"- Temperature: `{args.temperature}`",
        f"- response_format json_object: `{not args.no_response_format}`",
        "",
        "| model | requests | all ok | contract ok | decision ok | HTTP err | transport err | JSON invalid | format invalid | decision invalid | length stops | p50 s | max s | avg reasoning chars |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| {row['model']} | {row['requests']} | {row['ok']} | {row['contract_ok']} | {row['decision_ok']} | "
            f"{row['http_errors']} | {row['transport_errors']} | {row['json_invalid']} | {row['format_invalid']} | "
            f"{row['decision_invalid']} | {row['finish_length']} | {row['latency_p50_s']} | {row['latency_max_s']} | {row['avg_reasoning_len']} |"
        )
    failures = [r for r in records if not r.get("ok")]
    if failures:
        lines += ["", "## Failure samples", ""]
        for r in failures[:12]:
            lines += [
                f"### {r.get('model')} / {r.get('scenario_id')} / #{r.get('request_index')}",
                "",
                f"- HTTP: `{r.get('http_status')}` latency: `{r.get('latency_s')}` finish: `{r.get('finish_reason')}`",
                f"- transport_error: `{r.get('transport_error')}`",
                f"- parse_note: `{r.get('parse_note')}`",
                f"- format_problems: `{r.get('format_problems')}`",
                f"- decision_problems: `{r.get('decision_problems')}`",
                "",
                "```text",
                (r.get("content") or r.get("raw_body") or "")[:1200],
                "```",
                "",
            ]
    path.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    out_root = Path(args.output_dir) / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root.mkdir(parents=True, exist_ok=True)
    jobs = []
    scenario_order = list(SCENARIOS)
    rng.shuffle(scenario_order)
    for model in args.model:
        scenario_seq = [scenario_order[i % len(scenario_order)] for i in range(args.requests)]
        for idx, scenario in enumerate(scenario_seq):
            jobs.append((model, scenario, idx))
    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(call_once, args.base_url, model, scenario, idx, args) for model, scenario, idx in jobs]
        for fut in concurrent.futures.as_completed(futs):
            rec = fut.result()
            records.append(rec)
            print(json.dumps({k: rec.get(k) for k in ["model", "scenario_id", "request_index", "http_status", "latency_s", "finish_reason", "contract_ok", "decision_ok", "ok", "format_problems", "decision_problems", "transport_error"]}, sort_keys=True))
    records.sort(key=lambda r: (r["model"], r["request_index"], r["scenario_id"]))
    summary = summarize(records)
    (out_root / "records.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    write_markdown(out_root / "summary.md", records, summary, args)
    print("SUMMARY", json.dumps(summary, sort_keys=True))
    print("ARTIFACT_DIR", out_root)
    return 0 if all(r.get("ok") for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
