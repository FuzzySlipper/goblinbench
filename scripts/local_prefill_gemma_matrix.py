#!/usr/bin/env python3
"""Compare long-prompt prefill behavior for Gemma 4 26B/31B on den-nimo.

Runs a bounded matrix across:
- standalone vLLM on port 8000
- Lemonade on port 13305

The runner deliberately separates model load from the real measurement by sending a
small ACK warmup after each model is loaded, then running long-prompt probes with
unique prompts per size/repeat. It unloads/stops services between model/backend
runs to avoid memory leftovers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


VLLM_MODELS = [
    {
        "backend": "standalone-vllm",
        "model_id": "google/gemma-4-26B-A4B-it",
        "served_name": "gemma4-26b-a4b-it",
        "label": "vllm-gemma4-26b-a4b-it",
        "max_model_len": "8192",
        "max_num_seqs": "2",
        "max_num_batched_tokens": "8192",
        "kv_cache_memory_bytes": "8G",
        "gpu_memory_utilization": "0.90",
        "cpu_offload_gb": "",
        "ready_timeout": 1200,
    },
    {
        "backend": "standalone-vllm",
        "model_id": "google/gemma-4-31B-it",
        "served_name": "gemma4-31b-it",
        "label": "vllm-gemma4-31b-it",
        "max_model_len": "8192",
        "max_num_seqs": "2",
        "max_num_batched_tokens": "8192",
        "kv_cache_memory_bytes": "8G",
        "gpu_memory_utilization": "0.90",
        # Current den-nimo TTM/GTT is configured high enough for a resident
        # first attempt. Only set this manually for fallback runs if resident
        # loading fails.
        "cpu_offload_gb": "",
        "ready_timeout": 1500,
    },
]

LEMONADE_MODELS = [
    {
        "backend": "lemonade-llamacpp",
        "model_id": "gemma-4-26B-A4B-it-GGUF",
        "served_name": "gemma-4-26B-A4B-it-GGUF",
        "label": "lemonade-gemma4-26b-a4b-it-gguf-q6",
        "ready_timeout": 900,
    },
    {
        "backend": "lemonade-llamacpp",
        "model_id": "gemma-4-31B-it-GGUF",
        "served_name": "gemma-4-31B-it-GGUF",
        "label": "lemonade-gemma4-31b-it-gguf-q6",
        "ready_timeout": 1200,
    },
]


def run(cmd: list[str], *, timeout: int | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def ssh(command: str, *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return run(["ssh", "den-nimo", command], timeout=timeout)


def http_json(url: str, payload: dict[str, Any] | None = None, timeout: float = 30) -> tuple[int | None, dict[str, Any] | None, str]:
    try:
        if payload is None:
            req = urllib.request.Request(url, method="GET")
        else:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(text), text
            except Exception:
                return resp.status, None, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        return e.code, None, text
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}:{e}"


def lemonade_unload() -> dict[str, Any]:
    status, payload, text = http_json("http://192.168.1.23:13305/api/v0/unload", {}, timeout=60)
    return {"status": status, "payload": payload, "text": text[:1000]}


def stop_lemonade() -> str:
    unload = lemonade_unload()
    res = ssh("sudo systemctl stop lemond.service; sudo systemctl is-active lemond.service || true", timeout=90)
    return json.dumps({"unload": unload, "stdout": res.stdout[-2000:], "stderr": res.stderr[-2000:], "returncode": res.returncode})


def start_lemonade() -> str:
    res = ssh("sudo systemctl start lemond.service; for i in $(seq 1 60); do curl -fsS --max-time 5 http://127.0.0.1:13305/api/v0/health >/tmp/lem-health.json && cat /tmp/lem-health.json && exit 0; sleep 2; done; sudo systemctl --no-pager --full status lemond.service | sed -n '1,80p'; exit 1", timeout=150)
    return (res.stdout or "") + (res.stderr or "")


def stop_vllm() -> str:
    res = ssh("sudo systemctl stop vllm-json-probe.service; sudo systemctl is-active vllm-json-probe.service || true", timeout=120)
    return (res.stdout or "") + (res.stderr or "")


def set_vllm_env(spec: dict[str, Any]) -> str:
    # Preserve unrelated env entries, especially HF_TOKEN. Use base64 to avoid
    # multi-line shell quoting failures through ssh/sudo.
    import base64

    updates = {
        "VLLM_MODEL": spec["model_id"],
        "VLLM_SERVED_MODEL_NAME": spec["served_name"],
        "VLLM_MAX_MODEL_LEN": spec["max_model_len"],
        "VLLM_GPU_MEMORY_UTILIZATION": spec["gpu_memory_utilization"],
        "VLLM_MAX_NUM_SEQS": spec["max_num_seqs"],
        "VLLM_MAX_NUM_BATCHED_TOKENS": spec["max_num_batched_tokens"],
        "VLLM_KV_CACHE_MEMORY_BYTES": spec["kv_cache_memory_bytes"],
        "VLLM_CPU_OFFLOAD_GB": spec.get("cpu_offload_gb", ""),
    }
    py = f"""
import json
from pathlib import Path
updates = json.loads({json.dumps(json.dumps(updates))})
p = Path('/etc/vllm-json-probe.env')
lines = p.read_text().splitlines()
out = []
seen = set()
for line in lines:
    key = line.split('=', 1)[0] if '=' in line else None
    if key in updates:
        out.append(f'{{key}}={{updates[key]}}')
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{{key}}={{value}}')
p.write_text('\\n'.join(out) + '\\n')
"""
    encoded = base64.b64encode(py.encode()).decode()
    res = ssh(f"echo {encoded} | base64 -d | sudo python3", timeout=60)
    return (res.stdout or "") + (res.stderr or "")


def start_vllm_and_wait(spec: dict[str, Any]) -> tuple[bool, str]:
    env_log = set_vllm_env(spec)
    res = ssh("sudo systemctl restart vllm-json-probe.service", timeout=120)
    log = env_log + "\n" + (res.stdout or "") + (res.stderr or "")
    deadline = time.monotonic() + int(spec["ready_timeout"])
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        status = ssh(
            "state=$(sudo systemctl is-active vllm-json-probe.service || true); echo SERVICE_STATE=$state; "
            "curl -fsS --max-time 5 http://127.0.0.1:8000/v1/models || true",
            timeout=30,
        )
        blob = (status.stdout or "") + (status.stderr or "")
        log += "\n--- readiness attempt %d ---\n%s" % (attempts, blob[-4000:])
        if "SERVICE_STATE=failed" in blob or "SERVICE_STATE=inactive" in blob:
            diag = ssh("sudo systemctl --no-pager --full status vllm-json-probe.service | sed -n '1,120p'; sudo journalctl -u vllm-json-probe.service -n 160 --no-pager", timeout=60)
            log += "\n" + ((diag.stdout or "") + (diag.stderr or ""))[-16000:]
            return False, log
        match = re.search(r'(\{"object":"list".*\})', blob, re.S)
        if match:
            try:
                payload = json.loads(match.group(1))
                if spec["served_name"] in [m.get("id") for m in payload.get("data", [])]:
                    return True, log
            except Exception as exc:  # noqa: BLE001
                log += f"\nmodels parse error: {exc}\n"
        if attempts % 6 == 0:
            diag = ssh("date -Is; sudo systemctl --no-pager --full status vllm-json-probe.service | sed -n '1,36p'; sudo journalctl -u vllm-json-probe.service -n 40 --no-pager | tail -40; free -h | sed -n '2p'", timeout=60)
            log += "\n" + ((diag.stdout or "") + (diag.stderr or ""))[-8000:]
        time.sleep(10)
    return False, log


def ack_warmup(base_url: str, model: str, timeout: int) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "SEND ACK IF RECEIVED. Reply with ACK only."}],
        "temperature": 0,
        "max_tokens": 8,
        "stream": False,
    }
    started = time.perf_counter()
    status, parsed, text = http_json(base_url.rstrip("/") + "/chat/completions", payload, timeout=timeout)
    return {
        "status": status,
        "latency_s": round(time.perf_counter() - started, 3),
        "payload": parsed,
        "text_tail": text[-1000:],
    }


def run_probe(workdir: Path, root: Path, spec: dict[str, Any], base_url: str, args: argparse.Namespace) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/local_prefill_latency_probe.py",
        "--base-url",
        base_url,
        "--model",
        spec["served_name"],
        "--label",
        spec["label"],
        "--sizes",
        args.sizes,
        "--repeats",
        str(args.repeats),
        "--concurrency",
        str(args.concurrency),
        "--max-tokens",
        str(args.max_tokens),
        "--timeout",
        str(args.request_timeout),
        "--seed",
        str(args.seed),
        "--output-dir",
        str(root / "probe-runs"),
        "--no-response-format",
    ]
    proc = run(cmd, cwd=workdir, timeout=args.request_timeout * (len(args.sizes.split(',')) * args.repeats + 1) + 120)
    combined = (proc.stdout or "") + (proc.stderr or "")
    artifact = None
    summary = None
    for line in combined.splitlines():
        if line.startswith("ARTIFACT_DIR "):
            artifact = line.split(" ", 1)[1].strip()
        elif line.startswith("SUMMARY "):
            try:
                summary = json.loads(line.split(" ", 1)[1])
            except Exception:
                pass
    return {
        "returncode": proc.returncode,
        "artifact": artifact,
        "summary": summary,
        "stdout_tail": (proc.stdout or "")[-8000:],
        "stderr_tail": (proc.stderr or "")[-8000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", default="/home/dev/goblinbench")
    parser.add_argument("--sizes", default="512,2048,4096")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--seed", type=int, default=20260705)
    parser.add_argument("--skip-vllm", action="store_true")
    parser.add_argument("--skip-lemonade", action="store_true")
    args = parser.parse_args()

    workdir = Path(args.workdir)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    root = workdir / "runs" / "local-prefill-latency" / f"gemma-vllm-vs-lemonade-{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    def save() -> None:
        (root / "matrix-results.json").write_text(json.dumps(results, indent=2))
        lines = ["# Gemma 4 long-prompt prefill: standalone vLLM vs Lemonade", "", f"Started: `{stamp}`", "", f"Sizes: `{args.sizes}`; repeats: `{args.repeats}`; concurrency: `{args.concurrency}`", ""]
        lines.append("| backend | model | status | load/warmup | artifact | key rows |")
        lines.append("|---|---|---|---:|---|---|")
        for r in results:
            rows = (((r.get("probe") or {}).get("summary") or {}).get("rows") or [])
            rowbits = []
            for row in rows:
                rowbits.append(f"target {row.get('target_prompt_tokens')}→prompt {row.get('reported_prompt_tokens_median')}, first_event {row.get('first_event_p50_s')}, ttft {row.get('ttft_p50_s')}, total {row.get('total_p50_s')}, cached {row.get('cached_tokens_median')}")
            warm = (r.get("ack_warmup") or {}).get("latency_s")
            lines.append(f"| {r.get('backend')} | `{r.get('model_id')}` | {r.get('status')} | {warm} | `{(r.get('probe') or {}).get('artifact')}` | {'<br>'.join(rowbits)} |")
        (root / "matrix-summary.md").write_text("\n".join(lines) + "\n")

    try:
        if not args.skip_vllm:
            print("=== VLLM phase: stop/unload Lemonade first ===", flush=True)
            lemon_stop_log = stop_lemonade()
            (root / "lemonade-stop-before-vllm.log").write_text(lemon_stop_log)
            for spec in VLLM_MODELS:
                entry = dict(spec)
                entry["started_at"] = dt.datetime.now(dt.UTC).isoformat()
                print(f"=== standalone vLLM {spec['model_id']} ===", flush=True)
                ready, readiness_log = start_vllm_and_wait(spec)
                (root / f"{spec['label']}-readiness.log").write_text(readiness_log)
                entry["ready"] = ready
                if not ready:
                    entry["status"] = "vllm_not_ready_or_failed"
                    results.append(entry)
                    save()
                    stop_log = stop_vllm()
                    (root / f"{spec['label']}-stop-after-fail.log").write_text(stop_log)
                    continue
                entry["ack_warmup"] = ack_warmup("http://192.168.1.23:8000/v1", spec["served_name"], spec["ready_timeout"])
                entry["probe"] = run_probe(workdir, root, spec, "http://192.168.1.23:8000/v1", args)
                entry["status"] = "complete" if (entry["probe"].get("returncode") == 0) else "probe_failed"
                results.append(entry)
                save()
                stop_log = stop_vllm()
                (root / f"{spec['label']}-stop-after-run.log").write_text(stop_log)

        if not args.skip_lemonade:
            print("=== Lemonade phase: ensure vLLM stopped, start Lemonade ===", flush=True)
            (root / "vllm-stop-before-lemonade.log").write_text(stop_vllm())
            (root / "lemonade-start.log").write_text(start_lemonade())
            for spec in LEMONADE_MODELS:
                entry = dict(spec)
                entry["started_at"] = dt.datetime.now(dt.UTC).isoformat()
                print(f"=== Lemonade {spec['model_id']} ===", flush=True)
                entry["pre_unload"] = lemonade_unload()
                entry["ack_warmup"] = ack_warmup("http://192.168.1.23:13305/v1", spec["served_name"], spec["ready_timeout"])
                if entry["ack_warmup"].get("status") != 200:
                    entry["status"] = "ack_or_load_failed"
                    results.append(entry)
                    save()
                    entry["post_unload"] = lemonade_unload()
                    continue
                entry["probe"] = run_probe(workdir, root, spec, "http://192.168.1.23:13305/v1", args)
                entry["status"] = "complete" if (entry["probe"].get("returncode") == 0) else "probe_failed"
                entry["post_unload"] = lemonade_unload()
                results.append(entry)
                save()
    finally:
        # Leave the machine in a memory-free-ish state unless manually restored.
        try:
            (root / "final-lemonade-unload.json").write_text(json.dumps(lemonade_unload(), indent=2))
        except Exception as exc:  # noqa: BLE001
            (root / "final-lemonade-unload-error.txt").write_text(repr(exc))
        try:
            (root / "final-vllm-stop.log").write_text(stop_vllm())
        except Exception as exc:  # noqa: BLE001
            (root / "final-vllm-stop-error.txt").write_text(repr(exc))
        save()

    print("ARTIFACT_DIR", root, flush=True)
    print((root / "matrix-summary.md").read_text(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
