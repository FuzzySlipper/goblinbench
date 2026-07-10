#!/usr/bin/env python3
"""Smoke-probe OpenAI-compatible roleplay candidate configs.

Uses a tiny safe prompt and candidate-specific generation knobs, but caps max_tokens
for the smoke so long-thinking models do not spend the full benchmark budget.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="candidates.roleplay-matrix.json")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--out", default="runs/roleplay-candidate-smoke.json")
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--only", default="", help="Comma-separated candidate ids to probe")
    args = ap.parse_args()

    candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        candidates = [c for c in candidates if c.get("id") in wanted]
    results: list[dict[str, Any]] = []
    for cand in candidates:
        res = smoke_one(cand, timeout=args.timeout, max_tokens=args.max_tokens)
        results.append(res)
        status = "OK" if res["ok"] else "FAIL"
        print(f"{status:4} {res['id']:<72} {res['duration_s']:>6.1f}s {res.get('summary','')}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    failed = [r for r in results if not r["ok"]]
    print(f"\nWrote {out} ({len(results)} probes, {len(failed)} failed)")
    return 1 if failed else 0


def smoke_one(cand: dict[str, Any], *, timeout: float, max_tokens: int) -> dict[str, Any]:
    cfg = cand.get("config") or {}
    body: dict[str, Any] = {
        "model": cand.get("model"),
        "messages": [{"role": "user", "content": "Reply exactly: READY"}],
        "max_tokens": min(int(cfg.get("max_tokens") or max_tokens), max_tokens),
    }
    reasoning_effort = cfg.get("reasoning_effort")
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if (not reasoning_effort) or cfg.get("include_temperature_with_reasoning_effort"):
        body["temperature"] = cfg.get("temperature", 0.7)
    if isinstance(cfg.get("chat_template_kwargs"), dict):
        body["chat_template_kwargs"] = cfg["chat_template_kwargs"]
    if isinstance(cfg.get("request_overrides"), dict):
        body.update(cfg["request_overrides"])

    started = time.perf_counter()
    url = str(cand.get("base_url") or cand.get("endpoint") or "").rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
        duration = time.perf_counter() - started
        text, reasoning_chars, finish = extract_text_meta(raw)
        ok = 200 <= status < 300 and bool((text or "").strip())
        return {
            "id": cand.get("id"),
            "model": cand.get("model"),
            "provider": cand.get("provider"),
            "ok": ok,
            "status": status,
            "duration_s": round(duration, 3),
            "finish_reason": finish,
            "content_chars": len(text or ""),
            "reasoning_chars": reasoning_chars,
            "summary": (text or raw)[:160].replace("\n", " "),
        }
    except urllib.error.HTTPError as he:
        raw = he.read().decode("utf-8", errors="replace")
        return {
            "id": cand.get("id"),
            "model": cand.get("model"),
            "provider": cand.get("provider"),
            "ok": False,
            "status": he.code,
            "duration_s": round(time.perf_counter() - started, 3),
            "summary": f"HTTP {he.code}: {raw[:300]}",
        }
    except Exception as ex:  # noqa: BLE001 - smoke CLI should capture all failures
        return {
            "id": cand.get("id"),
            "model": cand.get("model"),
            "provider": cand.get("provider"),
            "ok": False,
            "status": None,
            "duration_s": round(time.perf_counter() - started, 3),
            "summary": repr(ex),
        }


def extract_text_meta(raw: str) -> tuple[str, int, str | None]:
    try:
        doc = json.loads(raw[raw.find("{"):]) if not raw.lstrip().startswith("{") else json.loads(raw)
    except Exception:
        return raw, 0, None
    choices = doc.get("choices") or []
    if not choices:
        return "", 0, None
    choice = choices[0]
    msg = choice.get("message") or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    if isinstance(reasoning, dict):
        reasoning = json.dumps(reasoning, ensure_ascii=False)
    return str(content), len(str(reasoning)), choice.get("finish_reason")


if __name__ == "__main__":
    raise SystemExit(main())
