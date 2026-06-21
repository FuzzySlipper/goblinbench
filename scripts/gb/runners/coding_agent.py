"""Bwrap-sandboxed coding-agent runner — port of CodingAgentRunner.cs.

Launches a coding agent CLI (pi, codex, claude) inside a bubblewrap sandbox
against a copied fixture workspace, captures the resulting file edits as a
unified diff, and records ``output["fixture_dir"]`` for the test scorer.

The agent is given exactly one writable mount: the per-candidate fixture
directory bound to ``/work`` inside the sandbox. Everything else (toolchain,
agent tree, dotnet SDK, npm cache) is read-only. This is "helpful friction
against dumb mistakes" — a confused model under context pressure cannot
accidentally rm -rf the host filesystem, the agent's own install, or any other
fixture. We are NOT isolating network or defending against a malicious actor.

Required candidate config (kind = coding-agent):
  - cli_args: arguments passed to the agent's entry script.
  - config.agent_resolved: absolute path to the agent's actual entry script.
  - config.sandbox_root: absolute host path to .sandbox-runtime/.
  - config.node_resolved (optional): absolute path to node. Auto-resolved otherwise.
  - config.task (optional): prompt text (else scenario.input.task is used).
  - config.api_key_env (optional): env var name whose value is passed to the agent.

Output includes:
  - output["fixture_dir"]: path the agent edited (consumed by the test scorer).
  - output["patch"]: unified diff of the agent's edits.
  - output["files_changed"]: list of relative file paths touched.
  - output["bwrap_argv"]: exact bwrap argv used (for trace/debug).
  - raw_response: agent stdout (model text, message_update events filtered out).
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from ..context import RunContext
from ..fsutil import (
    SKIP_DIRS_AGENT,
    DiffResult,
    compute_unified_diff,
    copy_directory,
    sha256_of_file,
    snapshot_directory,
)
from ..models import CandidateConfig, CandidateResult, ModelIdentity, Scenario, TraceEvent
from ..sandbox import BwrapProfile, BwrapValidationError, HostBind
from ..serialize import dumps, now_iso

# Inline raw_response is truncated to this many chars (full stream → stdout.log).
MAX_INLINE_RAW_RESPONSE_CHARS = 32_768


class CodingAgentRunner:
    name = "coding-agent"

    def can_handle(self, candidate: CandidateConfig) -> bool:
        return candidate.kind and candidate.kind.value == "CodingAgent"

    def run(self, scenario, candidate, context, timeout=None):
        # type: (Scenario, CandidateConfig, RunContext, float|None) -> CandidateResult
        started_perf = time.perf_counter()
        trace: list[TraceEvent] = []

        def fail(error: str) -> CandidateResult:
            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                success=False,
                error=error,
                duration_ms=int((time.perf_counter() - started_perf) * 1000),
                trace=trace,
                artifact_directory=context.candidate_artifacts_directory(candidate.id),
            )

        try:
            cfg = SandboxConfig.from_candidate(candidate)

            # 1. Resolve the task prompt (candidate config or scenario input).
            scenario_task = _get_string_from_input(scenario, "task")
            if not scenario_task and not cfg.task:
                return fail(
                    "No task prompt: provide scenario.input.task or candidate.config.task."
                )

            resolved = resolve_agent_paths(cfg, trace)

            # 2. Locate + copy fixture to per-candidate workspace.
            repo_root = context.repo_root or _find_repo_root(context.runs_root)
            fixture_case = _get_string_from_input(scenario, "fixture_case")
            if not fixture_case:
                return fail("Scenario input missing 'fixture_case'.")

            fixture_source = os.path.join(repo_root, "fixtures", "coding", fixture_case)
            if not os.path.isdir(fixture_source):
                return fail(f"Fixture directory not found: {fixture_source}")

            fixture_dest = os.path.join(context.candidate_directory(candidate.id), "fixture")
            copy_directory(fixture_source, fixture_dest, SKIP_DIRS_AGENT)
            _ensure_sandbox_scratch_dirs(fixture_dest)
            _ensure_fixture_runtime(fixture_dest, resolved.sandbox_root, trace)

            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.fixture.copied",
                data={"source": fixture_source, "destination": fixture_dest},
            ))

            # 3. Snapshot fixture before the agent runs.
            snapshot_before = snapshot_directory(fixture_dest, SKIP_DIRS_AGENT)
            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.snapshot.before",
                data={"file_count": len(snapshot_before)},
            ))

            # 4. Build + validate the bwrap profile.
            effective_task = cfg.task if cfg.task else scenario_task
            bwrap = build_bwrap_profile(cfg, resolved, fixture_dest, effective_task, trace)
            bwrap.validate()
            bwrap_argv = bwrap.to_argv(resolved.bwrap_path)
            bwrap_command_line = bwrap.to_command_line(resolved.bwrap_path)
            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.bwrap.starting",
                data={"argv": bwrap_argv, "command_line": bwrap_command_line},
            ))

            # 5. Launch the agent inside the sandbox.
            # argv[0] is bwrap itself; pass the rest as args. Cwd is the fixture
            # dir (the host-side source of the writable /work bind).
            proc_timeout = timeout if timeout is not None else (
                scenario.timeout_seconds if scenario.timeout_seconds > 0 else 300
            )
            stdout, stderr, exit_code, timed_out = _run_bwrap(
                resolved.bwrap_path, bwrap_argv[1:], fixture_dest, proc_timeout
            )

            duration_ms = int((time.perf_counter() - started_perf) * 1000)

            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.bwrap.exited",
                data={
                    "exit_code": exit_code,
                    "stdout_length": stdout.raw_length,
                    "stdout_retained_length": len(stdout.text),
                    "stdout_filtered_message_update_lines": stdout.filtered_lines,
                    "stdout_filtered_message_update_chars": stdout.filtered_chars,
                    "stderr_length": stderr.raw_length,
                    "duration_ms": duration_ms,
                    "timed_out": timed_out,
                },
            ))

            # 6. Snapshot after, diff, write artifacts.
            snapshot_after = snapshot_directory(fixture_dest, SKIP_DIRS_AGENT)
            diff = compute_unified_diff(snapshot_before, snapshot_after, fixture_dest)
            files_changed = diff.files_changed

            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.snapshot.after",
                data={
                    "file_count": len(snapshot_after),
                    "files_changed": len(files_changed),
                    "diff_lines": diff.unified_diff_text.count("\n"),
                },
            ))

            _write_artifacts(
                candidate, context, fixture_dest, diff, stdout, stderr, bwrap_command_line
            )

            success = exit_code == 0 and not timed_out
            produced_changes = len(files_changed) > 0

            if timed_out:
                error = f"Agent timed out after {proc_timeout}s."
            elif success and produced_changes:
                error = None
            elif success and not produced_changes:
                error = "Agent exited 0 but produced no file changes."
            else:
                tail = stderr.text[:500] if stderr.text else "(no stderr)"
                error = f"Agent exited with code {exit_code}: {tail}"

            return CandidateResult(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                candidate_kind=candidate.kind,
                model_identity=ModelIdentity(
                    model=candidate.model,
                    provider=candidate.provider or "coding-agent",
                    display_name=f"coding-agent:{candidate.id}",
                ),
                success=success and produced_changes,
                error=error,
                duration_ms=duration_ms,
                raw_response=_truncate_for_inline(stdout.text),
                output={
                    "fixture_dir": fixture_dest,
                    "fixture_case": fixture_case,
                    "patch": diff.unified_diff_text,
                    "files_changed": files_changed,
                    "stdout_length": stdout.raw_length,
                    "stdout_retained_length": len(stdout.text),
                    "stdout_filtered_message_update_lines": stdout.filtered_lines,
                    "stdout_filtered_message_update_chars": stdout.filtered_chars,
                    "stderr_length": stderr.raw_length,
                    "raw_response_truncated": len(stdout.text) > MAX_INLINE_RAW_RESPONSE_CHARS,
                    "bwrap_argv": bwrap_argv,
                    "bwrap_command_line": bwrap_command_line,
                    "agent_command": cfg.cli_args,
                    "agent_resolved_path": resolved.agent_entry_script,
                    "agent_resolved_sha256": resolved.agent_entry_sha256,
                    "timed_out": timed_out,
                    "exit_code": exit_code,
                },
                trace=trace,
                artifact_directory=context.candidate_artifacts_directory(candidate.id),
            )
        except BwrapValidationError as ex:
            return fail(f"Bwrap profile invalid: {ex}")
        except FileNotFoundError as ex:
            return fail(f"CodingAgentRunner failed: {ex}")
        except Exception as ex:  # noqa: BLE001 — runner isolation mirrors C#
            return fail(f"CodingAgentRunner failed: {ex}")


# ── Path resolution ─────────────────────────────────────────────────────────


@dataclass
class ResolvedAgentPaths:
    bwrap_path: str
    node_path: str
    agent_entry_script: str
    agent_entry_sha256: str
    sandbox_root: str


@dataclass
class SandboxConfig:
    agent_resolved: str
    node_resolved: str
    sandbox_root: str
    dotnet_root: str | None
    api_key_env: str | None
    task: str
    cli_args: list[str]
    agent_dir: str | None

    @classmethod
    def from_candidate(cls, c: CandidateConfig) -> "SandboxConfig":
        agent_resolved = _get_config_string(c, "agent_resolved")
        if not agent_resolved:
            raise ValueError("candidate.config.agent_resolved is required for coding-agent kind.")
        sandbox_root = _get_config_string(c, "sandbox_root")
        if not sandbox_root:
            raise ValueError("candidate.config.sandbox_root is required (path to .sandbox-runtime/).")
        return cls(
            agent_resolved=agent_resolved,
            node_resolved=_get_config_string(c, "node_resolved") or "",
            sandbox_root=sandbox_root,
            dotnet_root=_get_config_string(c, "dotnet_root"),
            api_key_env=_get_config_string(c, "api_key_env"),
            task=_get_config_string(c, "task") or "",
            cli_args=list(c.cli_args),
            agent_dir=_get_config_string(c, "agent_dir"),
        )


def resolve_agent_paths(cfg: SandboxConfig, trace: list[TraceEvent]) -> ResolvedAgentPaths:
    bwrap_path = _resolve_bwrap_path()
    node_path = _resolve_node_path(cfg.node_resolved)

    if not os.path.isfile(node_path):
        raise FileNotFoundError(f"Node binary not found at '{node_path}'. Set config.node_resolved.")
    if not os.path.isfile(cfg.agent_resolved):
        raise FileNotFoundError(
            f"Agent entry script not found at '{cfg.agent_resolved}'. "
            "Set config.agent_resolved to the absolute path inside .sandbox-runtime/node_modules/..."
        )
    if not os.path.isdir(cfg.sandbox_root):
        raise FileNotFoundError(
            f"Sandbox root not found at '{cfg.sandbox_root}'. "
            "Run 'npm install --ignore-scripts' under .sandbox-runtime/ first."
        )

    # Resolve symlinks so bwrap binds the real file, not a relative path that
    # won't exist once the namespace is unshared. os.path.realpath follows all
    # symlinks (matches the C# chained ResolveLinkTarget loop).
    agent_entry_real = os.path.realpath(cfg.agent_resolved)
    node_real = os.path.realpath(node_path)
    sandbox_root_real = os.path.realpath(cfg.sandbox_root)
    agent_sha = sha256_of_file(agent_entry_real)

    trace.append(TraceEvent(
        timestamp=now_iso(),
        event="coding.paths.resolved",
        data={
            "bwrap": bwrap_path,
            "node": node_real,
            "agent": agent_entry_real,
            "agent_sha256": agent_sha,
            "sandbox_root": sandbox_root_real,
        },
    ))

    return ResolvedAgentPaths(
        bwrap_path=bwrap_path,
        node_path=node_real,
        agent_entry_script=agent_entry_real,
        agent_entry_sha256=agent_sha,
        sandbox_root=sandbox_root_real,
    )


def _resolve_bwrap_path() -> str:
    for c in ("/usr/bin/bwrap", "/usr/local/bin/bwrap"):
        if os.path.isfile(c):
            return c
    return "bwrap"  # PATH fallback


def _resolve_node_path(configured: str) -> str:
    if configured and os.path.isfile(configured):
        return configured
    which = _locate_on_path("node")
    if which:
        return which
    for c in ("/usr/bin/node", "/usr/local/bin/node"):
        if os.path.isfile(c):
            return c
    return configured or "node"


def _locate_on_path(name: str) -> str | None:
    path = os.environ.get("PATH", "")
    if not path:
        return None
    for d in path.split(os.pathsep):
        try:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return candidate
        except OSError:
            continue
    return None


# ── Bwrap profile construction ──────────────────────────────────────────────


def build_bwrap_profile(
    cfg: SandboxConfig,
    resolved: ResolvedAgentPaths,
    fixture_dest: str,
    task: str,
    trace: list[TraceEvent],
) -> BwrapProfile:
    # Read-only binds. Bind the entire host filesystem read-only so the agent
    # can read whatever it needs but cannot damage any existing host file. The
    # only writable mount is /work (the fixture, bound writable in the base profile).
    candidate_binds = [
        ("/", "/"),
        (resolved.sandbox_root, resolved.sandbox_root),  # re-bound for trace clarity
    ]
    binds: list[HostBind] = []
    for src, dest in candidate_binds:
        if os.path.exists(src):
            binds.append(HostBind(source=src, destination=dest))
        else:
            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.bwrap.bind_skipped",
                data={"source": src, "destination": dest,
                      "reason": "source does not exist on host"},
            ))

    # ~/.dotnet is the SDK install; implicit in the / bind but re-bound for visibility.
    home = os.environ.get("HOME") or "/root"
    user_dotnet = os.path.join(home, ".dotnet")
    if os.path.isdir(user_dotnet):
        binds.append(HostBind(source=user_dotnet, destination=user_dotnet))

    # Env: only the keys the agent needs. HOME/TMPDIR/XDG_CACHE_HOME live under
    # /tmp/agent-workspace so scratch state (npm cache, etc.) is thrown away with
    # the workspace.
    env: dict[str, str] = {
        "HOME": "/tmp/agent-workspace/.home",
        "PATH": resolved.sandbox_root + "/python-fixture-venv/bin:/usr/bin:/bin",
        "TMPDIR": "/tmp/agent-workspace/.tmp",
        "XDG_CACHE_HOME": "/tmp/agent-workspace/.cache",
        "DOTNET_CLI_HOME": "/tmp/agent-workspace/.dotnet-home",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
        "PI_SUPPRESS_JSON_MESSAGE_UPDATES": "1",
    }

    host_nuget = os.path.join(home, ".nuget", "packages")
    if os.path.isdir(host_nuget):
        env["NUGET_PACKAGES"] = host_nuget

    # pi looks for <PI_CODING_AGENT_DIR>/models.json when discovering custom
    # providers. Bind sandbox_root to itself so the host path == sandbox path.
    agent_dir_in_sandbox = cfg.agent_dir or (resolved.sandbox_root + "/agent")
    env["PI_CODING_AGENT_DIR"] = agent_dir_in_sandbox

    # Pass through API key if configured.
    if cfg.api_key_env:
        key = os.environ.get(cfg.api_key_env)
        if key:
            env[cfg.api_key_env] = key

    # Inner command: node <agent> <cli_args...> <task>
    inner_command = [resolved.node_path, resolved.agent_entry_script] + list(cfg.cli_args)
    inner_command.append(task)

    trace.append(TraceEvent(
        timestamp=now_iso(),
        event="coding.bwrap.profile_built",
        data={
            "workspace": fixture_dest,
            "ro_bind_count": len(binds),
            "env_var_count": len(env),
            "inner_argv_length": len(inner_command),
        },
    ))

    return BwrapProfile(
        work_dir="/tmp/agent-workspace",
        work_dir_source=fixture_dest,
        read_only_binds=binds,
        environment=env,
        command=inner_command,
    )


# ── Subprocess execution + output capture ───────────────────────────────────


@dataclass
class ProcessOutputCapture:
    text: str
    raw_length: int
    filtered_lines: int = 0
    filtered_chars: int = 0


def _run_bwrap(
    bwrap_path: str,
    argv_tail: list[str],
    cwd: str,
    timeout: float,
) -> tuple[ProcessOutputCapture, ProcessOutputCapture, int, bool]:
    """Launch bwrap, drain stdout (with message_update filtering) + stderr
    concurrently, enforce a deadline, kill the process tree on timeout.

    Returns (stdout_capture, stderr_capture, exit_code, timed_out).
    """
    proc = subprocess.Popen(
        [bwrap_path] + argv_tail,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # Deliberately NOT start_new_session=True: a new session was observed
        # to hang bwrap's pre-exec on GLM52 maintainability runs (confirmed by
        # the A/B reproducer). Without a new session the bwrap child shares the
        # runner's process group, so process-tree cleanup must NOT use killpg on
        # that group — see _kill_process_tree, which walks /proc descendants
        # instead (matching .NET's Kill(entireProcessTree: true)).
    )
    deadline = time.monotonic() + timeout
    timed_out = False

    stdout_lines: list[str] = []
    filtered_lines = 0
    filtered_chars = 0
    raw_length = 0

    # Drain stdout with select() so the deadline is checked every poll even
    # when the agent produces no output (handles the hang case — a faithful
    # substitute for C#'s CancellationTokenSource timeout on WaitForExitAsync).
    assert proc.stdout is not None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([proc.stdout], [], [], min(1.0, remaining))
            if ready:
                line = proc.stdout.readline()
                if line == "":  # EOF
                    break
                line_len = len(line)  # includes trailing newline
                raw_length += line_len
                if _is_json_line_of_type(line, "message_update"):
                    filtered_lines += 1
                    filtered_chars += line_len
                    continue
                stdout_lines.append(line)
    finally:
        # On timeout (or any exit from the loop), ensure the process is reaped.
        pass

    if timed_out:
        _kill_process_tree(proc)
    # Wait for exit (bounded by a small grace period after we've stopped reading).
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        proc.wait()

    # Drain stderr fully (process has exited).
    stderr_text = proc.stderr.read() if proc.stderr else ""
    stderr_raw = len(stderr_text)

    stdout_text = "".join(stdout_lines)
    stdout_capture = ProcessOutputCapture(
        text=stdout_text,
        raw_length=raw_length,
        filtered_lines=filtered_lines,
        filtered_chars=filtered_chars,
    )
    stderr_capture = ProcessOutputCapture(text=stderr_text, raw_length=stderr_raw)
    return stdout_capture, stderr_capture, proc.returncode, timed_out


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """SIGKILL the bwrap process and all its descendants.

    Faithful port of the C# ``Process.Kill(entireProcessTree: true)`` behavior
    on Linux, which walks the process tree and kills each descendant — it does
    NOT use process groups. This matters here: we deliberately launch bwrap
    WITHOUT ``start_new_session`` (a new session was observed to hang bwrap's
    pre-exec on GLM52 maintainability runs), so the bwrap process shares the
    runner's process group. Calling ``os.killpg`` on its pgid would therefore
    SIGKILL the runner itself. Walking /proc for descendants avoids that and
    also catches the node agent (and any of its children) running inside the
    sandbox even though they're in a different PID namespace — they still
    appear under the bwrap pid from the host's perspective.
    """
    pids = _collect_descendants(proc.pid)
    pids.append(proc.pid)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass  # already gone or not ours


def _collect_descendants(root_pid: int) -> list[int]:
    """Return descendant PIDs of root_pid (transitively) by reading /proc.

    Linux-only — bwrap itself is Linux-only, so the whole module is. If /proc
    isn't readable for any reason, returns [] (the caller still kills root_pid).
    """
    # Build pid → ppid map from /proc/<pid>/stat (fields: pid(comm)state ppid ...).
    # stat field 4 is ppid. The comm field may contain spaces/parens, so parse
    # from the last ')' to be safe.
    children: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return []
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                data = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        rparen = data.rfind(")")
        if rparen < 0:
            continue
        rest = data[rparen + 1:].split()
        if len(rest) < 2:
            continue
        try:
            ppid = int(rest[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    # BFS from root_pid.
    out: list[int] = []
    queue = list(children.get(root_pid, []))
    seen: set[int] = set()
    while queue:
        pid = queue.pop()
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        queue.extend(children.get(pid, []))
    return out


def _is_json_line_of_type(line: str, expected_type: str) -> bool:
    """Port of C# IsJsonLineOfType: fast pre-check then exact type match."""
    s = line.strip()
    if not s or s[0] != "{":
        return False
    try:
        doc = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("type") == expected_type


# ── Artifacts ───────────────────────────────────────────────────────────────


def _write_artifacts(
    candidate: CandidateConfig,
    context: RunContext,
    fixture_dir: str,
    diff: DiffResult,
    stdout: ProcessOutputCapture,
    stderr: ProcessOutputCapture,
    bwrap_command_line: str,
) -> None:
    output_path = context.candidate_output_path(candidate.id)
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)

    stdout_path = os.path.join(output_dir, "stdout.log")
    stderr_path = os.path.join(output_dir, "stderr.log")
    with open(stdout_path, "w", encoding="utf-8") as f:
        f.write(stdout.text)
    with open(stderr_path, "w", encoding="utf-8") as f:
        f.write(stderr.text)

    output = {
        "fixture_dir": fixture_dir,
        "patch": diff.unified_diff_text,
        "files_changed": diff.files_changed,
        "bwrap_command_line": bwrap_command_line,
        "stdout_path": os.path.basename(stdout_path),
        "stdout_length": stdout.raw_length,
        "stdout_retained_length": len(stdout.text),
        "stdout_filtered_message_update_lines": stdout.filtered_lines,
        "stdout_filtered_message_update_chars": stdout.filtered_chars,
        "stdout_tail": _truncate_for_inline(stdout.text),
        "stderr_path": os.path.basename(stderr_path),
        "stderr_length": stderr.raw_length,
        "stderr_tail": _truncate_for_inline(stderr.text),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(dumps(output))

    patch_path = os.path.join(output_dir, "agent.patch")
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(diff.unified_diff_text)


# ── Fixture runtime prep ────────────────────────────────────────────────────


def _ensure_sandbox_scratch_dirs(fixture_dest: str) -> None:
    for rel in (".tmp", ".cache", ".home", ".dotnet-home"):
        os.makedirs(os.path.join(fixture_dest, rel), exist_ok=True)


def _ensure_fixture_runtime(
    fixture_dest: str, sandbox_root: str, trace: list[TraceEvent]
) -> None:
    """Prepare a Python venv inside the sandbox root for pytest fixtures.

    Port of C# EnsureFixtureRuntime — an optimization for agent time, not a
    hard requirement. Scorers run from the host if this fails. The venv is
    cached at <sandbox_root>/python-fixture-venv and reused across runs.
    """
    if not os.path.isfile(os.path.join(fixture_dest, "pyproject.toml")) and \
       not os.path.isfile(os.path.join(fixture_dest, "pytest.ini")):
        return

    runtime_dir = os.path.join(sandbox_root, "python-fixture-venv")
    venv_python = os.path.join(runtime_dir, "bin", "python")
    if os.path.isfile(venv_python):
        return  # already prepared

    try:
        uv = _locate_on_path("uv")
        if uv:
            _run_setup(uv, ["venv", "--python", "3.14", runtime_dir], sandbox_root, 90)
            _run_setup(uv, ["pip", "install", "--python", venv_python, "pytest"], sandbox_root, 120)
            trace.append(TraceEvent(
                timestamp=now_iso(),
                event="coding.fixture_runtime.prepared",
                data={"kind": "python", "tool": "uv", "path": runtime_dir},
            ))
            return

        python = _locate_on_path("python3") or _locate_on_path("python")
        if not python:
            return
        _run_setup(python, ["-m", "venv", runtime_dir], sandbox_root, 90)
        _run_setup(venv_python, ["-m", "pip", "install", "pytest"], sandbox_root, 120)
        trace.append(TraceEvent(
            timestamp=now_iso(),
            event="coding.fixture_runtime.prepared",
            data={"kind": "python", "tool": "venv+pip", "path": runtime_dir},
        ))
    except Exception as ex:  # noqa: BLE001 — best-effort optimization
        trace.append(TraceEvent(
            timestamp=now_iso(),
            event="coding.fixture_runtime.prepare_failed",
            data={"kind": "python", "error": str(ex)},
        ))


def _run_setup(
    filename: str, args: list[str], cwd: str, timeout: float
) -> None:
    proc = subprocess.run(
        [filename] + args, cwd=cwd,
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[:500]
        raise RuntimeError(
            f"Setup command failed ({proc.returncode}): {filename} {' '.join(args)}: {tail}")


# ── Misc helpers ────────────────────────────────────────────────────────────


def _truncate_for_inline(text: str) -> str:
    if len(text) <= MAX_INLINE_RAW_RESPONSE_CHARS:
        return text
    omitted = len(text) - MAX_INLINE_RAW_RESPONSE_CHARS
    return (
        f"[truncated {omitted} chars; see stdout.log/stderr.log artifact for full stream]\n"
        + text[-MAX_INLINE_RAW_RESPONSE_CHARS:]
    )


def _get_string_from_input(scenario: Scenario, key: str) -> str:
    v = scenario.input.get(key)
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _get_config_string(candidate: CandidateConfig, key: str) -> str | None:
    v = candidate.config.get(key)
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return str(v)


def _find_repo_root(runs_root: str) -> str:
    d = os.path.dirname(runs_root) or runs_root
    while True:
        if os.path.isdir(os.path.join(d, "suites")) and os.path.isdir(os.path.join(d, "src")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(runs_root) or runs_root
