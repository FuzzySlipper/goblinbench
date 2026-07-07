#!/usr/bin/env python3
"""Focused standalone-vLLM Gemma 4 context-window rerun on den-nimo.

Purpose:
- Retry Gemma 4 31B without CPU offload now that den-nimo TTM/GTT is large.
- Increase vLLM max_model_len enough to avoid the previous 8192-token wall.
- Compare 26B-A4B MoE and 31B dense under the same vLLM-only setup.

This intentionally avoids rerunning Lemonade; use the prior matrix artifact for those
rows: runs/local-prefill-latency/gemma-vllm-vs-lemonade-20260705T092128Z/
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "scripts" / "local_prefill_gemma_matrix.py"
PROBE = ROOT / "scripts" / "local_prefill_latency_probe.py"
RUN_ROOT = ROOT / "runs" / "local-prefill-latency"


def load_matrix_module() -> Any:
    spec = importlib.util.spec_from_file_location("local_prefill_gemma_matrix", MATRIX_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {MATRIX_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_probe(*, model: str, label: str, out_dir: Path, sizes: str, repeats: int, concurrency: int, max_tokens: int, timeout: int) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(PROBE),
        "--base-url",
        "http://192.168.1.23:8000/v1",
        "--model",
        model,
        "--label",
        label,
        "--sizes",
        sizes,
        "--repeats",
        str(repeats),
        "--concurrency",
        str(concurrency),
        "--max-tokens",
        str(max_tokens),
        "--timeout",
        str(timeout),
        "--seed",
        "20260705",
        "--output-dir",
        str(out_dir / "probe-runs"),
        "--no-response-format",
    ]
    print("$", " ".join(cmd), flush=True)
    res = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout * max(2, len(sizes.split(",")) * repeats + 1))
    summary = None
    artifact = None
    for line in (res.stdout or "").splitlines():
        if line.startswith("ARTIFACT_DIR "):
            artifact = line.split(" ", 1)[1].strip()
        if line.startswith("SUMMARY "):
            try:
                summary = json.loads(line.split(" ", 1)[1])
            except Exception:
                pass
    return {
        "returncode": res.returncode,
        "artifact": artifact,
        "summary": summary,
        "stdout_tail": (res.stdout or "")[-5000:],
        "stderr_tail": (res.stderr or "")[-5000:],
    }


def compact_rows(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "no summary"
    parts = []
    for row in summary.get("rows", []):
        parts.append(
            "target {target_prompt_tokens}→prompt {reported_prompt_tokens_median}, "
            "first_event {first_event_p50_s}, ttft {ttft_p50_s}, total {total_p50_s}, "
            "http_errors {http_errors}".format(**row)
        )
    return "<br>".join(parts)


def write_summary(out_dir: Path, results: list[dict[str, Any]], *, sizes: str, repeats: int, concurrency: int, max_tokens: int) -> None:
    lines = [
        "# Gemma 4 standalone vLLM larger-context rerun",
        "",
        f"Started: `{out_dir.name.replace('gemma-vllm-context-rerun-', '')}`",
        "",
        f"Sizes: `{sizes}`; repeats: `{repeats}`; concurrency: `{concurrency}`; max_tokens: `{max_tokens}`",
        "",
        "| model | status | max_model_len | kv_cache | offload | warmup s | artifact | key rows |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for item in results:
        probe = item.get("probe") or {}
        lines.append(
            "| `{model}` | {status} | {max_model_len} | {kv_cache_memory_bytes} | {cpu_offload_gb} | {warmup} | `{artifact}` | {rows} |".format(
                model=item.get("model_id"),
                status=item.get("status"),
                max_model_len=item.get("max_model_len"),
                kv_cache_memory_bytes=item.get("kv_cache_memory_bytes"),
                cpu_offload_gb=item.get("cpu_offload_gb") or "none",
                warmup=(item.get("ack_warmup") or {}).get("latency_s"),
                artifact=probe.get("artifact"),
                rows=compact_rows(probe.get("summary")),
            )
        )
    (out_dir / "rerun-summary.md").write_text("\n".join(lines) + "\n")
    (out_dir / "rerun-results.json").write_text(json.dumps(results, indent=2) + "\n")


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="512,2048,4096,6144")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=64)
    ap.add_argument("--request-timeout", type=int, default=1200)
    ap.add_argument("--ready-timeout", type=int, default=1800)
    ap.add_argument("--max-model-len", default="16384")
    ap.add_argument("--kv-cache-memory-bytes", default="16G")
    ap.add_argument("--models", default="26b,31b", help="comma subset: 26b,31b")
    args = ap.parse_args()

    matrix = load_matrix_module()
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUN_ROOT / f"gemma-vllm-context-rerun-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metadata.json").write_text(json.dumps(vars(args), indent=2) + "\n")

    print("=== vLLM-only context rerun: stop Lemonade ===", flush=True)
    (out_dir / "lemonade-stop-before-vllm.log").write_text(matrix.stop_lemonade())

    model_specs = []
    wanted = {m.strip().lower() for m in args.models.split(",") if m.strip()}
    for base in matrix.VLLM_MODELS:
        if "26B" in base["model_id"] and "26b" not in wanted:
            continue
        if "31B" in base["model_id"] and "31b" not in wanted:
            continue
        spec = dict(base)
        spec["max_model_len"] = args.max_model_len
        spec["max_num_seqs"] = str(args.concurrency)
        spec["max_num_batched_tokens"] = args.max_model_len
        spec["kv_cache_memory_bytes"] = args.kv_cache_memory_bytes
        spec["gpu_memory_utilization"] = "0.92"
        spec["cpu_offload_gb"] = ""
        spec["label"] = spec["label"].replace("-cpuoffload24", "") + f"-ctx{args.max_model_len}-resident"
        spec["ready_timeout"] = args.ready_timeout
        model_specs.append(spec)

    results: list[dict[str, Any]] = []
    try:
        for spec in model_specs:
            print(f"=== standalone vLLM {spec['model_id']} ctx={spec['max_model_len']} resident ===", flush=True)
            ready, readiness_log = matrix.start_vllm_and_wait(spec)
            (out_dir / f"{spec['label']}-readiness.log").write_text(readiness_log)
            item: dict[str, Any] = {**spec, "started_at": dt.datetime.now(dt.UTC).isoformat(), "ready": ready}
            if not ready:
                item["status"] = "not-ready"
                results.append(item)
                write_summary(out_dir, results, sizes=args.sizes, repeats=args.repeats, concurrency=args.concurrency, max_tokens=args.max_tokens)
                continue
            item["ack_warmup"] = matrix.ack_warmup("http://192.168.1.23:8000/v1", spec["served_name"], timeout=args.request_timeout)
            item["probe"] = run_probe(
                model=spec["served_name"],
                label=spec["label"],
                out_dir=out_dir,
                sizes=args.sizes,
                repeats=args.repeats,
                concurrency=args.concurrency,
                max_tokens=args.max_tokens,
                timeout=args.request_timeout,
            )
            item["status"] = "complete" if item["probe"].get("returncode") == 0 else "probe-failed"
            results.append(item)
            write_summary(out_dir, results, sizes=args.sizes, repeats=args.repeats, concurrency=args.concurrency, max_tokens=args.max_tokens)
            (out_dir / f"{spec['label']}-stop-after-run.log").write_text(matrix.stop_vllm())
    finally:
        print("=== cleanup: stop vLLM, start Lemonade ===", flush=True)
        (out_dir / "vllm-stop-final.log").write_text(matrix.stop_vllm())
        (out_dir / "lemonade-start-final.log").write_text(matrix.start_lemonade())

    write_summary(out_dir, results, sizes=args.sizes, repeats=args.repeats, concurrency=args.concurrency, max_tokens=args.max_tokens)
    print((out_dir / "rerun-summary.md").read_text(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
