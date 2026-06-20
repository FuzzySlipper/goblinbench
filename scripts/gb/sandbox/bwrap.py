"""Bubblewrap (bwrap) profile builder — port of Sandbox/BwrapProfile.cs.

Builds a ``bwrap`` argv for a coding-agent subprocess. This is a near-verbatim
port of the C# builder; the safety properties and comments are preserved.

Design intent (from the C# docstring): helpful friction against dumb mistakes,
not hard isolation. The agent is untrusted only in the sense that we want
defaults to fail safe when a confused model does something unexpected (e.g.
rm -rf the wrong directory). We are NOT defending against a malicious agent or
network exfiltration — the network namespace is shared with the host on purpose
so that ``dotnet restore`` / ``npm install`` still work.

Properties enforced:
  * The host root ``/`` is bound read-only.
  * Exactly one writable mount is allowed: the per-scenario workspace.
  * All other bind mounts are read-only.
  * Env is cleared (--clearenv) and only declared vars are set.
  * Working directory is set explicitly inside the sandbox.
  * --die-with-parent cleans up if the harness dies.

Historical note (from C#): an earlier design started with ``--tmpfs /`` and
enumerated every needed read-only path. That broke on distros where bwrap's
execvp couldn't find inner commands through specific path binds. Binding the
whole host read-only is simpler and strictly stronger.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


class BwrapValidationError(Exception):
    """Raised when a profile fails Validate() (catches obvious foot-guns)."""


class BindMode:
    READ_ONLY = "ReadOnly"


@dataclass(frozen=True)
class HostBind:
    source: str
    destination: str
    mode: str = BindMode.READ_ONLY


@dataclass
class BwrapProfile:
    # Path inside the sandbox used as the agent's working dir + writable workspace.
    # Defaults to /tmp/agent-workspace — parent /tmp is always a fresh tmpfs (see
    # TmpfsScratchDirs), which is required for bwrap to create the mount point
    # when the host root is read-only.
    work_dir: str = "/tmp/agent-workspace"
    # Absolute path on the host bound to work_dir as the writable workspace.
    work_dir_source: str = ""
    # Inner command (executable + args) run inside the sandbox.
    command: List[str] = field(default_factory=list)
    # Read-only bind mounts the agent needs (host path, sandbox path).
    read_only_binds: List[HostBind] = field(default_factory=list)
    # Environment variables explicitly set inside the sandbox. --clearenv is
    # always applied first, so anything not listed here is dropped.
    environment: dict[str, str] = field(default_factory=dict)
    # If True, share the network namespace with the host (NuGet/npm need it).
    share_network: bool = True
    # Override hostname inside the sandbox.
    hostname: str = "goblinbench-sandbox"
    # Fresh tmpfs scratch areas so the agent can write without polluting host.
    tmpfs_scratch_dirs: List[str] = field(
        default_factory=lambda: ["/tmp", "/var/tmp", "/run"]
    )

    def to_argv(self, bwrap_path: str = "bwrap") -> List[str]:
        """Build the full argv. Suitable for subprocess argv[1:] or trace artifacts."""
        argv: list[str] = [
            bwrap_path,
            "--unshare-all",
            "--die-with-parent",
            "--hostname", self.hostname,
        ]

        if self.share_network:
            argv.append("--share-net")

        # Bind the whole host read-only first (caller adds --ro-bind / / as the
        # first read-only bind), then bind the workspace writable on top so the
        # inner command can find its libraries/tooling through /, but the only
        # writable mount is work_dir.
        for bind in self.read_only_binds:
            if bind.mode == BindMode.READ_ONLY:
                argv += ["--ro-bind", bind.source, bind.destination]
            else:
                raise BwrapValidationError(
                    f"BwrapProfile only allows read-only binds except for work_dir; "
                    f"got writable bind from {bind.source} to {bind.destination}."
                )

        # Tmpfs scratch areas (/tmp, /var/tmp, /run).
        for scratch in self.tmpfs_scratch_dirs:
            argv += ["--tmpfs", scratch]

        # Fresh /dev so subprocess plumbing works inside the user namespace
        # (e.g. /dev/null for shell redirects and Node's stdio:"ignore").
        argv += ["--dev", "/dev"]

        # Writable workspace — must come after ro-binds, tmpfs, and /dev overlays
        # so the bind shadows whatever's under work_dir in the read-only root.
        argv += ["--bind", self.work_dir_source, self.work_dir]

        # Env handling: clear first, then explicitly set declared vars.
        argv.append("--clearenv")
        for k, v in self.environment.items():
            argv += ["--setenv", k, v]

        argv += ["--chdir", self.work_dir, "--"]
        argv += list(self.command)
        return argv

    def to_command_line(self, bwrap_path: str = "bwrap") -> str:
        """Single shell-escaped command line for logging/trace (does NOT parse)."""
        out: list[str] = []
        for a in self.to_argv(bwrap_path):
            if not out:
                out.append(a)
                continue
            if _needs_quote(a):
                out.append('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"')
            else:
                out.append(a)
        return " ".join(out)

    def validate(self) -> None:
        """Catch obvious foot-guns. Raises BwrapValidationError; otherwise no-op."""
        if not self.work_dir or not self.work_dir.strip():
            raise BwrapValidationError("work_dir must be set.")
        if not self.work_dir.startswith("/"):
            raise BwrapValidationError(
                f"work_dir must be an absolute path inside the sandbox; got '{self.work_dir}'.")
        if not self.work_dir_source or not self.work_dir_source.strip():
            raise BwrapValidationError("work_dir_source must be an absolute host path.")
        if not os.path.isabs(self.work_dir_source):
            raise BwrapValidationError(f"work_dir_source must be absolute; got '{self.work_dir_source}'.")
        if not self.command:
            raise BwrapValidationError("command must contain at least the executable.")

        for bind in self.read_only_binds:
            if not os.path.isabs(bind.source):
                raise BwrapValidationError(f"Read-only bind source must be absolute: {bind.source}")
            if not bind.destination.startswith("/"):
                raise BwrapValidationError(
                    f"Read-only bind destination must be absolute inside sandbox: {bind.destination}")
            if bind.destination == self.work_dir or bind.destination.startswith(self.work_dir + "/"):
                raise BwrapValidationError(
                    f"Read-only bind {bind.destination} collides with the writable work_dir {self.work_dir}.")
            # Binding over / is allowed when read-only (the "host root read-only" pattern).
            # Only the writable workspace is forbidden from being /.
            if bind.destination == "/" and bind.mode == BindMode.READ_ONLY:
                continue

        if self.work_dir == "/":
            raise BwrapValidationError(
                "work_dir cannot be /; pick a subdirectory like /tmp/agent-workspace.")

        # The parent of work_dir must be writable (tmpfs). If a caller picks a
        # custom work_dir under a non-tmpfs path, refuse.
        if not any(self.work_dir == d or self.work_dir.startswith(d + "/")
                   for d in self.tmpfs_scratch_dirs):
            raise BwrapValidationError(
                f"work_dir '{self.work_dir}' must live under one of the tmpfs scratch dirs: "
                f"[{', '.join(self.tmpfs_scratch_dirs)}]. Pick a path like /tmp/agent-workspace.")

        # Inner command should be absolute. Relative paths inside the sandbox can
        # refer to a different FS — make this explicit.
        if not os.path.isabs(self.command[0]):
            raise BwrapValidationError(
                f"Inner command executable must be an absolute path: '{self.command[0]}'.")


def _needs_quote(arg: str) -> bool:
    return any(c in arg for c in (" ", "\t", '"', "\\"))
