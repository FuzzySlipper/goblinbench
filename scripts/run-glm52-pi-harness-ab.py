#!/usr/bin/env python3
"""Controlled A/B probes for GLM52 through pi CLI vs GoblinBench-style bwrap.

This is an investigation script, not a permanent benchmark runner.
It deliberately varies one harness factor at a time and caps stdout so pi JSON
message streams cannot fill disk.
"""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import BinaryIO, cast

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/coding/maintainability-mini-service-python"
SCENARIO = ROOT / "suites/coding/maintainability-mini-service-python.json"
RUNTIME = ROOT / ".sandbox-runtime"
NODE = Path("/usr/bin/node")
PI = RUNTIME / "node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
EXT = RUNTIME / "den-router-coding-workspace/den-router.ts"
AGENT_DIR = RUNTIME / "agent"
PY_VENV = RUNTIME / "python-fixture-venv"

SMOKE_PROMPT = """In this workspace, create a file named glm52_smoke.txt containing exactly the text ok followed by a newline. Use the available editing tools, then stop."""


def maintainability_prompt() -> str:
    return json.loads(SCENARIO.read_text())["input"]["task"]


@dataclass
class Variant:
    name: str
    prompt_kind: str
    bwrap: bool
    mode: str
    suppress_updates: bool
    no_session: bool = True
    timeout_s: int = 180
    raw_cap_mb: int = 80


@dataclass
class Result:
    name: str
    prompt_kind: str
    bwrap: bool
    mode: str
    suppress_updates: bool
    no_session: bool
    exit_code: int | None
    timed_out: bool
    raw_capped: bool
    duration_s: float
    stdout_raw_bytes: int
    stdout_retained_bytes: int
    stderr_raw_bytes: int
    stderr_retained_bytes: int
    files_changed: list[str]
    smoke_file: str | None
    pytest_summary: str | None
    artifact_dir: str


def snapshot_files(workspace: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    skip = {"__pycache__", ".pytest_cache", ".venv", "node_modules", "target", ".git"}
    for p in workspace.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(workspace).as_posix()
        if any(part in skip for part in rel.split("/")):
            continue
        st = p.stat()
        out[rel] = (st.st_size, st.st_mtime_ns)
    return out


def changed(before: dict[str, tuple[int, int]], workspace: Path) -> list[str]:
    after = snapshot_files(workspace)
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))


def base_inner_args(variant: Variant, prompt: str) -> list[str]:
    args = [
        str(NODE), str(PI),
        "--print",
    ]
    if variant.no_session:
        args.append("--no-session")
    else:
        args += ["--session-dir", ".pi-sessions", "--session-id", f"gb-{variant.name}"]
    args += [
        "--no-extensions",
        "--extension", str(EXT),
        "--provider", "den-router",
        "--model", "glm52",
        "--mode", variant.mode,
        prompt,
    ]
    return args


def bwrap_args(workspace: Path, inner: list[str], variant: Variant) -> list[str]:
    env = {
        "HOME": "/tmp/agent-workspace/.home",
        "PATH": f"{PY_VENV}/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp/agent-workspace/.tmp",
        "XDG_CACHE_HOME": "/tmp/agent-workspace/.cache",
        "DOTNET_CLI_HOME": "/tmp/agent-workspace/.dotnet-home",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
        "PI_CODING_AGENT_DIR": str(AGENT_DIR),
    }
    if variant.suppress_updates:
        env["PI_SUPPRESS_JSON_MESSAGE_UPDATES"] = "1"

    args = [
        "/usr/bin/bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--hostname", "goblinbench-ab",
        "--share-net",
        "--ro-bind", "/", "/",
        "--ro-bind", str(RUNTIME), str(RUNTIME),
        "--tmpfs", "/tmp",
        "--tmpfs", "/var/tmp",
        "--tmpfs", "/run",
        "--dev", "/dev",
        "--bind", str(workspace), "/tmp/agent-workspace",
        "--clearenv",
    ]
    for k, v in env.items():
        args += ["--setenv", k, v]
    args += ["--chdir", "/tmp/agent-workspace", "--"] + inner
    return args


def run_capture(cmd: list[str], cwd: Path | None, env: dict[str, str], out_dir: Path, timeout_s: int, raw_cap: int) -> tuple[int | None, bool, bool, float, int, int, int, int]:
    out_path = out_dir / "stdout.log"
    err_path = out_dir / "stderr.log"
    raw_out = raw_err = retained_out = retained_err = 0
    timed_out = raw_capped = False
    start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    sel = selectors.DefaultSelector()
    assert proc.stdout and proc.stderr
    sel.register(proc.stdout, selectors.EVENT_READ, "out")
    sel.register(proc.stderr, selectors.EVENT_READ, "err")
    with out_path.open("wb") as outf, err_path.open("wb") as errf:
        while True:
            if time.monotonic() - start > timeout_s:
                timed_out = True
                proc.kill()
                break
            if raw_out > raw_cap:
                raw_capped = True
                proc.kill()
                break
            events = sel.select(timeout=0.25)
            for key, _ in events:
                fd = key.fileobj.fileno()  # type: ignore[attr-defined]
                chunk = os.read(fd, 65536)
                if not chunk:
                    try:
                        sel.unregister(key.fileobj)
                    except Exception:
                        pass
                    continue
                if key.data == "out":
                    raw_out += len(chunk)
                    if retained_out < raw_cap:
                        keep = chunk[: max(0, raw_cap - retained_out)]
                        outf.write(keep)
                        retained_out += len(keep)
                else:
                    raw_err += len(chunk)
                    keep_cap = 5 * 1024 * 1024
                    if retained_err < keep_cap:
                        keep = chunk[: max(0, keep_cap - retained_err)]
                        errf.write(keep)
                        retained_err += len(keep)
            if proc.poll() is not None and not sel.get_map():
                break
            if proc.poll() is not None:
                # drain any remaining readable chunks next loop; if none, unregisters above
                if not events:
                    break
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return proc.returncode, timed_out, raw_capped, time.monotonic() - start, raw_out, retained_out, raw_err, retained_err


def maybe_pytest(workspace: Path, out_dir: Path) -> str | None:
    try:
        cp = subprocess.run(
            [str(PY_VENV / "bin/python"), "-m", "pytest", "tests/", "-q"],
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
        (out_dir / "pytest-after.log").write_text(cp.stdout)
        lines = [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]
        return lines[-1] if lines else f"exit {cp.returncode}"
    except Exception as exc:
        return f"pytest-error: {exc}"


def run_variant(root: Path, variant: Variant) -> Result:
    out_dir = root / variant.name
    workspace = out_dir / "workspace"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE, workspace)
    for d in [".home", ".tmp", ".cache", ".dotnet-home"]:
        (workspace / d).mkdir(exist_ok=True)
    prompt = SMOKE_PROMPT if variant.prompt_kind == "smoke" else maintainability_prompt()
    before = snapshot_files(workspace)
    inner = base_inner_args(variant, prompt)
    if variant.bwrap:
        cmd = bwrap_args(workspace, inner, variant)
        cwd = None
        env = os.environ.copy()
    else:
        cmd = inner
        cwd = workspace
        env = os.environ.copy()
        env.update({
            "HOME": str(workspace / ".home"),
            "TMPDIR": str(workspace / ".tmp"),
            "XDG_CACHE_HOME": str(workspace / ".cache"),
            "PI_CODING_AGENT_DIR": str(AGENT_DIR),
            "PATH": f"{PY_VENV}/bin:/usr/bin:/bin:{env.get('PATH','')}",
        })
        if variant.suppress_updates:
            env["PI_SUPPRESS_JSON_MESSAGE_UPDATES"] = "1"
        else:
            env.pop("PI_SUPPRESS_JSON_MESSAGE_UPDATES", None)
    (out_dir / "command.json").write_text(json.dumps({"cmd": cmd, "cwd": str(cwd) if cwd else None, "env_delta": {k: env.get(k) for k in ["HOME", "PATH", "PI_CODING_AGENT_DIR", "PI_SUPPRESS_JSON_MESSAGE_UPDATES"]}}, indent=2))
    cap = variant.raw_cap_mb * 1024 * 1024
    exit_code, timed_out, raw_capped, dur, so_raw, so_ret, se_raw, se_ret = run_capture(cmd, cwd, env, out_dir, variant.timeout_s, cap)
    changes = changed(before, workspace)
    smoke_file = None
    sf = workspace / "glm52_smoke.txt"
    if sf.exists():
        smoke_file = sf.read_text(errors="replace")[:200]
    pytest_summary = maybe_pytest(workspace, out_dir) if variant.prompt_kind == "maint" else None
    return Result(
        name=variant.name,
        prompt_kind=variant.prompt_kind,
        bwrap=variant.bwrap,
        mode=variant.mode,
        suppress_updates=variant.suppress_updates,
        no_session=variant.no_session,
        exit_code=exit_code,
        timed_out=timed_out,
        raw_capped=raw_capped,
        duration_s=round(dur, 3),
        stdout_raw_bytes=so_raw,
        stdout_retained_bytes=so_ret,
        stderr_raw_bytes=se_raw,
        stderr_retained_bytes=se_ret,
        files_changed=changes,
        smoke_file=smoke_file,
        pytest_summary=pytest_summary,
        artifact_dir=str(out_dir),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "runs/pi-glm52-harness-ab"))
    ap.add_argument("--full", action="store_true", help="run extra expensive/unsafe variants")
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_root = Path(args.out) / stamp
    out_root.mkdir(parents=True, exist_ok=True)
    variants = [
        Variant("smoke-no-bwrap-json-suppress", "smoke", False, "json", True, timeout_s=90),
        Variant("smoke-bwrap-json-suppress", "smoke", True, "json", True, timeout_s=90),
        Variant("maint-no-bwrap-json-suppress", "maint", False, "json", True, timeout_s=240),
        Variant("maint-bwrap-json-suppress", "maint", True, "json", True, timeout_s=240),
        Variant("maint-no-bwrap-text", "maint", False, "text", False, timeout_s=240),
        Variant("maint-bwrap-text", "maint", True, "text", False, timeout_s=240),
    ]
    if args.full:
        variants += [
            Variant("maint-no-bwrap-json-unsuppressed", "maint", False, "json", False, timeout_s=240, raw_cap_mb=80),
            Variant("maint-bwrap-json-unsuppressed", "maint", True, "json", False, timeout_s=240, raw_cap_mb=80),
            Variant("maint-no-bwrap-json-session", "maint", False, "json", True, no_session=False, timeout_s=240),
            Variant("maint-bwrap-json-session", "maint", True, "json", True, no_session=False, timeout_s=240),
        ]
    results: list[Result] = []
    for v in variants:
        print(f"=== {v.name} ===", flush=True)
        r = run_variant(out_root, v)
        results.append(r)
        print(json.dumps(asdict(r), indent=2), flush=True)
        (out_root / "results.json").write_text(json.dumps([asdict(x) for x in results], indent=2))
    print(f"RESULTS {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
