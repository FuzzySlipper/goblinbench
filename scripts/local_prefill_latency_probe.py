#!/usr/bin/env python3
"""Local OpenAI-compatible prompt-prefill latency probe.

Targets local endpoints such as standalone vLLM or Lemonade and sends long,
deterministic prompts with tiny outputs. The main signals are:

- TTFT (time to first streamed token/chunk): mostly scheduler + prefill latency.
- total latency: TTFT + tiny decode tail.
- reported prompt_tokens when the endpoint returns usage.
- transport/HTTP failures at different prompt sizes/concurrency.

This is intentionally standalone rather than a full GoblinBench suite runner so we
can poke local inference endpoints quickly while tuning service flags.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """You are a latency probe responder. Reply with JSON only.
Do not explain. Do not repeat the prompt. Keep the answer tiny."""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", required=True, help="OpenAI-compatible base URL, e.g. http://host:8000/v1")
    p.add_argument("--model", required=True)
    p.add_argument("--label", default=None, help="Human label for reports, defaults to model")
    p.add_argument("--sizes", default="512,2048,8192,16384", help="Approx prompt token sizes, comma-separated")
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--max-tokens", type=int, default=16)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--output-dir", default="runs/local-prefill-latency")
    p.add_argument("--no-stream", action="store_true", help="Use non-streaming requests; loses TTFT signal")
    p.add_argument("--no-response-format", action="store_true")
    p.add_argument("--seed", type=int, default=20260630)
    return p.parse_args()


def approx_words_for_tokens(tokens: int) -> int:
    # English-ish text is usually ~1.25-1.5 tokens/word for these snippets.
    # Slightly overshoot; usage.prompt_tokens records the endpoint's true count
    # when available.
    return max(1, int(tokens / 1.25))


def build_prompt(target_tokens: int, seed: int) -> str:
    words_needed = approx_words_for_tokens(target_tokens)
    lines: list[str] = []
    lines.append("Long-context prefill probe. Read the facts, ignore distractors, and answer only the final JSON task.")
    lines.append(f"Target approximate prompt tokens: {target_tokens}. Seed: {seed}.")
    line_template = (
        "Fact {i:05d}: route={route}; crate={crate}; priority={priority}; "
        "checksum={checksum}; note=stable prefill measurement filler with a small amount of structured variation."
    )
    produced_words = sum(len(x.split()) for x in lines)
    i = 0
    while produced_words < words_needed:
        checksum = (seed * 1315423911 + i * 2654435761) % 1000003
        route = chr(ord("A") + (i % 6))
        crate = f"C{(i * 17 + seed) % 997:03d}"
        priority = ["low", "normal", "high", "hold"][i % 4]
        line = line_template.format(i=i, route=route, crate=crate, priority=priority, checksum=checksum)
        lines.append(line)
        produced_words += len(line.split())
        i += 1
    lines.append("Final task: Return exactly this JSON shape with no extra keys:")
    lines.append('{"ok": true, "selected_route": "C", "ignored": "distractors", "probe": "prefill"}')
    return "\n".join(lines)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * pct
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return vals[lo]
    return vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def parse_sse_line(line: bytes) -> dict[str, Any] | None:
    text = line.decode("utf-8", errors="replace").strip()
    if not text or text.startswith(":"):
        return None
    if not text.startswith("data:"):
        return None
    data = text[5:].strip()
    if data == "[DONE]":
        return {"__done__": True}
    try:
        return json.loads(data)
    except Exception as exc:  # noqa: BLE001
        return {"__parse_error__": f"{type(exc).__name__}:{exc}", "raw": data[:500]}


def call_once(args: argparse.Namespace, size: int, repeat_index: int) -> dict[str, Any]:
    # Include size in the seed so an ascending size ladder does not create
    # identical long prefixes that make prefix-cache hits look like prefill speed.
    prompt_seed = args.seed + (repeat_index * 1009) + (size * 1000003)
    prompt = build_prompt(size, prompt_seed)
    payload: dict[str, Any] = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": not args.no_stream,
    }
    if payload["stream"]:
        payload["stream_options"] = {"include_usage": True}
    if not args.no_response_format:
        payload["response_format"] = {"type": "json_object"}
    url = args.base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    record: dict[str, Any] = {
        "label": args.label or args.model,
        "model": args.model,
        "base_url": args.base_url,
        "target_prompt_tokens": size,
        "prompt_chars": len(prompt),
        "prompt_seed": prompt_seed,
        "repeat_index": repeat_index,
        "stream": bool(payload["stream"]),
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    first_event_at: float | None = None
    first_chunk_at: float | None = None
    content_chunks: list[str] = []
    usage: dict[str, Any] | None = None
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            record["http_status"] = resp.status
            if payload["stream"]:
                for raw_line in resp:
                    event = parse_sse_line(raw_line)
                    if not event:
                        continue
                    if event.get("__done__"):
                        break
                    if first_event_at is None:
                        first_event_at = time.perf_counter()
                    if "__parse_error__" in event:
                        record.setdefault("stream_parse_errors", []).append(event)
                        continue
                    if event.get("usage"):
                        usage = event.get("usage")
                    choices = event.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        piece = delta.get("content") or ""
                        if piece and first_chunk_at is None:
                            first_chunk_at = time.perf_counter()
                        if piece:
                            content_chunks.append(piece)
                body_text = "".join(content_chunks)
            else:
                raw_body = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw_body)
                usage = parsed.get("usage")
                body_text = parsed.get("choices", [{}])[0].get("message", {}).get("content", "")
                if body_text:
                    first_chunk_at = None
    except urllib.error.HTTPError as e:
        record.update(
            http_status=e.code,
            transport_error=f"HTTPError:{e.code}",
            raw_body=e.read().decode("utf-8", errors="replace")[:4000],
            total_latency_s=round(time.perf_counter() - started, 3),
            ok=False,
        )
        return record
    except Exception as e:  # noqa: BLE001
        record.update(
            http_status=None,
            transport_error=f"{type(e).__name__}:{e}",
            total_latency_s=round(time.perf_counter() - started, 3),
            ok=False,
        )
        return record

    ended = time.perf_counter()
    record["first_event_s"] = round(first_event_at - started, 3) if first_event_at is not None else None
    record["ttft_s"] = round(first_chunk_at - started, 3) if first_chunk_at is not None else None
    record["total_latency_s"] = round(ended - started, 3)
    record["usage"] = usage
    if usage:
        record["prompt_tokens"] = usage.get("prompt_tokens")
        record["completion_tokens"] = usage.get("completion_tokens")
        record["total_tokens"] = usage.get("total_tokens")
    record["raw_content"] = body_text[:2000]
    try:
        parsed_content = json.loads(body_text.strip())
        record["json_ok"] = isinstance(parsed_content, dict) and parsed_content.get("ok") is True
    except Exception as exc:  # noqa: BLE001
        record["json_ok"] = False
        record["json_error"] = f"{type(exc).__name__}:{exc}"
    record["ok"] = bool(record.get("http_status") == 200 and record.get("json_ok"))
    return record


def summarize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(int(r["target_prompt_tokens"]), []).append(r)
    rows: list[dict[str, Any]] = []
    for size, recs in sorted(groups.items()):
        good_total = [float(r["total_latency_s"]) for r in recs if r.get("total_latency_s") is not None and not r.get("transport_error")]
        good_event = [float(r["first_event_s"]) for r in recs if r.get("first_event_s") is not None and not r.get("transport_error")]
        good_ttft = [float(r["ttft_s"]) for r in recs if r.get("ttft_s") is not None and not r.get("transport_error")]
        prompt_tokens = [int(r["prompt_tokens"]) for r in recs if isinstance(r.get("prompt_tokens"), int)]
        cached_tokens = []
        for r in recs:
            usage = r.get("usage") or {}
            details = usage.get("prompt_tokens_details") or {}
            if isinstance(details.get("cached_tokens"), int):
                cached_tokens.append(int(details["cached_tokens"]))
        event_p50 = percentile(good_event, 0.5) if good_event else None
        ttft_p50 = percentile(good_ttft, 0.5) if good_ttft else None
        total_p50 = percentile(good_total, 0.5) if good_total else None
        rows.append(
            {
                "target_prompt_tokens": size,
                "requests": len(recs),
                "ok": sum(1 for r in recs if r.get("ok")),
                "http_errors": sum(1 for r in recs if r.get("http_status") not in (200, None)),
                "transport_errors": sum(1 for r in recs if r.get("transport_error")),
                "json_ok": sum(1 for r in recs if r.get("json_ok")),
                "reported_prompt_tokens_median": statistics.median(prompt_tokens) if prompt_tokens else None,
                "cached_tokens_median": statistics.median(cached_tokens) if cached_tokens else None,
                "first_event_p50_s": round(event_p50, 3) if event_p50 is not None else None,
                "first_event_max_s": round(max(good_event), 3) if good_event else None,
                "ttft_p50_s": round(ttft_p50, 3) if ttft_p50 is not None else None,
                "ttft_max_s": round(max(good_ttft), 3) if good_ttft else None,
                "total_p50_s": round(total_p50, 3) if total_p50 is not None else None,
                "total_max_s": round(max(good_total), 3) if good_total else None,
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "._-" else "-" for c in (args.label or args.model))[:80]
    outdir = Path(args.output_dir) / f"{stamp}-{safe_label}"
    outdir.mkdir(parents=True, exist_ok=True)

    jobs = [(size, rep) for size in sizes for rep in range(args.repeats)]
    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(call_once, args, size, rep) for size, rep in jobs]
        for fut in concurrent.futures.as_completed(futs):
            rec = fut.result()
            records.append(rec)
            print(json.dumps({k: rec.get(k) for k in [
                "label", "target_prompt_tokens", "prompt_tokens", "repeat_index", "http_status",
                "first_event_s", "ttft_s", "total_latency_s", "ok", "transport_error", "json_ok",
            ]}, sort_keys=True), flush=True)

    rows = summarize(records)
    (outdir / "records.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n")
    (outdir / "summary.json").write_text(json.dumps({"rows": rows, "args": vars(args)}, indent=2))
    lines = ["# Local prefill latency probe", "", f"Label: `{args.label or args.model}`", ""]
    lines.append("| target prompt toks | reported prompt toks | cached toks | req | ok | transport err | first event p50 | TTFT p50 | total p50 | total max |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row['target_prompt_tokens']} | {row['reported_prompt_tokens_median']} | {row['cached_tokens_median']} | {row['requests']} | {row['ok']} | {row['transport_errors']} | {row['first_event_p50_s']} | {row['ttft_p50_s']} | {row['total_p50_s']} | {row['total_max_s']} |"
        )
    (outdir / "summary.md").write_text("\n".join(lines) + "\n")
    print("SUMMARY", json.dumps({"rows": rows}, sort_keys=True), flush=True)
    print("ARTIFACT_DIR", outdir, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
