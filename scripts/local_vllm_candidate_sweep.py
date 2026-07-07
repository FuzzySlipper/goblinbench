#!/usr/bin/env python3
"""Run a bounded standalone-vLLM candidate sweep on den-nimo.

Switches vllm-json-probe.service to each model, waits for readiness, runs the
GoblinBench local JSON concurrency probe, and writes a compact sweep report.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_MODELS = [
    {
        "model_id": "google/gemma-4-12B-it",
        "served_name": "gemma4-12b-it",
        "requests": 16,
        "concurrency": 4,
        "max_tokens": 512,
        "probe_timeout": 600,
        "ready_timeout": 900,
    },
    {
        "model_id": "ibm-granite/granite-4.1-8b",
        "served_name": "granite-41-8b",
        "requests": 16,
        "concurrency": 4,
        "max_tokens": 512,
        "probe_timeout": 600,
        "ready_timeout": 900,
    },
    {
        "model_id": "LiquidAI/LFM2.5-8B-A1B",
        "served_name": "lfm25-8b-a1b",
        "requests": 16,
        "concurrency": 4,
        "max_tokens": 512,
        "probe_timeout": 600,
        "ready_timeout": 900,
    },
    {
        "model_id": "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16",
        "served_name": "nemotron3-nano-4b-bf16",
        "requests": 16,
        "concurrency": 4,
        "max_tokens": 512,
        "probe_timeout": 600,
        "ready_timeout": 900,
    },
    {
        "model_id": "Qwen/Qwen3.5-4B",
        "served_name": "qwen35-4b",
        "requests": 16,
        "concurrency": 4,
        "max_tokens": 512,
        "probe_timeout": 600,
        "ready_timeout": 900,
    },
]


def run(cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def ssh(command: str, *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return run(["ssh", "den-nimo", command], timeout=timeout)


def wait_ready(served_name: str, timeout_s: int) -> tuple[bool, dict | None, str]:
    deadline = time.monotonic() + timeout_s
    attempts = 0
    last = ""
    while time.monotonic() < deadline:
        attempts += 1
        status = ssh(
            "set -e; "
            "state=$(sudo systemctl is-active vllm-json-probe.service || true); "
            "echo SERVICE_STATE=$state; "
            "if [ \"$state\" != active ]; then "
            "  sudo systemctl --no-pager --full status vllm-json-probe.service | sed -n '1,80p'; "
            "  sudo journalctl -u vllm-json-probe.service -n 100 --no-pager; "
            "  exit 3; "
            "fi; "
            "curl -fsS --max-time 5 http://127.0.0.1:8000/v1/models || true",
            timeout=30,
        )
        last = (status.stdout or "") + (status.stderr or "")
        if status.returncode == 3:
            return False, None, last
        match = re.search(r'(\{"object":"list".*\})', last, re.S)
        if match:
            try:
                payload = json.loads(match.group(1))
                ids = [m.get("id") for m in payload.get("data", [])]
                if served_name in ids:
                    print(f"READY {served_name} after {attempts} attempts", flush=True)
                    return True, payload, last
            except Exception as exc:  # noqa: BLE001
                last += f"\nJSON_PARSE_ERROR {type(exc).__name__}: {exc}\n"
        if attempts % 6 == 0:
            diag = ssh(
                "date -Is; "
                "sudo systemctl --no-pager --full status vllm-json-probe.service | sed -n '1,32p'; "
                "sudo journalctl -u vllm-json-probe.service -n 35 --no-pager | tail -35; "
                "df -h /home/llm | tail -1; free -h | sed -n '2p'",
                timeout=60,
            )
            print(diag.stdout[-6000:], flush=True)
        time.sleep(10)
    return False, None, last


def summarize_probe_output(output: str) -> tuple[str | None, dict | None]:
    artifact = None
    summary = None
    for line in output.splitlines():
        if line.startswith("ARTIFACT_DIR "):
            artifact = line.split(" ", 1)[1].strip()
        if line.startswith("SUMMARY "):
            try:
                summary = json.loads(line.split(" ", 1)[1])["rows"][0]
            except Exception:
                pass
    if artifact and summary is None:
        p = Path(artifact) / "summary.json"
        if p.exists():
            summary = json.loads(p.read_text())["rows"][0]
    return artifact, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://192.168.1.23:8000/v1")
    parser.add_argument("--workdir", default="/home/dev/goblinbench")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    workdir = Path(args.workdir)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    outdir = Path(args.output_dir) if args.output_dir else workdir / "runs" / "local-json-concurrency" / f"candidate-sweep-{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for spec in DEFAULT_MODELS:
        model_id = spec["model_id"]
        served = spec["served_name"]
        print("\n=== MODEL", model_id, "as", served, "===", flush=True)
        entry = dict(spec)
        entry["started_at"] = dt.datetime.now(dt.UTC).isoformat()
        switch = ssh(
            f"sudo /usr/local/sbin/vllm-json-probe-set-model {model_id} {served}",
            timeout=120,
        )
        entry["switch_returncode"] = switch.returncode
        entry["switch_stdout_tail"] = switch.stdout[-4000:]
        entry["switch_stderr_tail"] = switch.stderr[-4000:]
        if switch.returncode != 0:
            entry["status"] = "switch_failed"
            results.append(entry)
            continue

        ready, models_payload, readiness_log = wait_ready(served, spec["ready_timeout"])
        entry["ready"] = ready
        entry["models_payload"] = models_payload
        entry["readiness_log_tail"] = readiness_log[-8000:]
        if not ready:
            entry["status"] = "not_ready_or_failed"
            results.append(entry)
            (outdir / "sweep-results.json").write_text(json.dumps(results, indent=2))
            continue

        cmd = [
            sys.executable,
            "scripts/local_json_concurrency_probe.py",
            "--base-url",
            args.base_url,
            "--model",
            served,
            "--requests",
            str(spec["requests"]),
            "--concurrency",
            str(spec["concurrency"]),
            "--max-tokens",
            str(spec["max_tokens"]),
            "--timeout",
            str(spec["probe_timeout"]),
        ]
        probe = run(cmd, cwd=workdir, timeout=spec["probe_timeout"] + 90)
        combined = (probe.stdout or "") + (probe.stderr or "")
        artifact, summary = summarize_probe_output(combined)
        entry["probe_returncode"] = probe.returncode
        entry["artifact"] = artifact
        entry["summary"] = summary
        entry["probe_output_tail"] = combined[-12000:]
        entry["status"] = "probe_complete" if summary else "probe_no_summary"
        entry["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
        results.append(entry)
        (outdir / "sweep-results.json").write_text(json.dumps(results, indent=2))

    lines = ["# Local vLLM candidate sweep", "", f"Started: `{stamp}`", ""]
    lines.append("| model | served | status | req | conc | contract ok | decision ok | json invalid | transport err | p50 s | max s | artifact |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for e in results:
        s = e.get("summary") or {}
        lines.append(
            "| {model} | {served} | {status} | {req} | {conc} | {contract} | {decision} | {json_invalid} | {transport} | {p50} | {maxlat} | {artifact} |".format(
                model=f"`{e['model_id']}`",
                served=f"`{e['served_name']}`",
                status=e.get("status", "?"),
                req=e.get("requests", ""),
                conc=e.get("concurrency", ""),
                contract=(f"{s.get('contract_ok')}/{s.get('requests')}" if s else ""),
                decision=(f"{s.get('decision_ok')}/{s.get('requests')}" if s else ""),
                json_invalid=s.get("json_invalid", "") if s else "",
                transport=s.get("transport_errors", "") if s else "",
                p50=s.get("latency_p50_s", "") if s else "",
                maxlat=s.get("latency_max_s", "") if s else "",
                artifact=f"`{e.get('artifact')}`" if e.get("artifact") else "",
            )
        )
    (outdir / "sweep-summary.md").write_text("\n".join(lines) + "\n")
    print("\nSWEEP_OUTDIR", outdir, flush=True)
    print((outdir / "sweep-summary.md").read_text(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
