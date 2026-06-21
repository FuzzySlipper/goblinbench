"""Filesystem helpers shared by the coding runners — port of the private
helpers in CodingAgentRunner.cs / CodingCandidateRunner.cs.

These are kept module-level (not inside a runner) because both the
deterministic ``coding-scripted`` runner and the real bwrap ``coding-agent``
runner snapshot, copy, and diff fixtures identically.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


# Directories/files excluded from fixture copies, snapshots, and diffs.
# Mirrors CodingAgentRunner.SkipDirs (the larger set): build artifacts,
# runner-owned scratch dirs, language caches, and lockfiles-that-are-rebuilt.
SKIP_DIRS_AGENT = {
    "obj", "bin", ".git", ".vs",
    ".tmp", ".cache", ".home", ".local",
    "__pycache__", ".pytest_cache", ".venv", "node_modules",
    "coverage", "dist", "target", "uv.lock",
}

# CodingCandidateRunner (deterministic) uses a smaller skip set.
SKIP_DIRS_SCRIPTED = {"obj", "bin", ".git", ".vs"}


@dataclass(frozen=True)
class FileSnap:
    rel_path: str
    size: int
    sha256: str


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place so os.walk doesn't descend into them.
        dirnames[:] = [d for d in dirnames]
        for fname in filenames:
            yield os.path.join(dirpath, fname)


def copy_directory(source: str, destination: str, skip_dirs: set[str]) -> None:
    """Copy a fixture tree, skipping any path segment in ``skip_dirs``.

    Port of CodingAgentRunner.CopyDirectory / CodingCandidateRunner.CopyDirectory.
    """
    os.makedirs(destination, exist_ok=True)
    for file in _iter_files(source):
        relative = os.path.relpath(file, source)
        segments = relative.replace("\\", "/").split("/")
        if any(seg in skip_dirs for seg in segments):
            continue
        dest_file = os.path.join(destination, relative)
        os.makedirs(os.path.dirname(dest_file) or ".", exist_ok=True)
        # Use copyfile to mirror File.Copy semantics (metadata not required).
        with open(file, "rb") as src, open(dest_file, "wb") as dst:
            dst.write(src.read())


def snapshot_directory(root: str, skip_dirs: set[str]) -> dict[str, FileSnap]:
    """Map relative-path → FileSnap for every file under root (skip dirs filtered)."""
    result: dict[str, FileSnap] = {}
    for file in _iter_files(root):
        relative = os.path.relpath(file, root).replace("\\", "/")
        segments = relative.split("/")
        if any(seg in skip_dirs for seg in segments):
            continue
        try:
            size = os.path.getsize(file)
            sha = sha256_of_file(file)
        except OSError:
            continue
        result[relative] = FileSnap(rel_path=relative, size=size, sha256=sha)
    return result


@dataclass
class DiffResult:
    unified_diff_text: str
    files_changed: list[str]


def compute_unified_diff(
    before: dict[str, FileSnap],
    after: dict[str, FileSnap],
    root: str,
) -> DiffResult:
    """Compute a unified-diff-style patch (new/deleted files) + changed-path list.

    Faithful port of CodingAgentRunner.ComputeUnifiedDiff. NOTE: this is a
    simplified diff — every added/modified file is emitted as a 'new file' with
    all content prefixed '+'; deletions emit a deletion hunk. This matches the
    C# behavior exactly. The patch is a debug/trace artifact; the test scorer
    reads fixture_dir directly and runs the suite, so semantic fidelity here is
    what matters, not a byte-exact real diff.
    """
    lines: list[str] = []
    changed: set[str] = set()

    # Added or modified files.
    for path, snap in after.items():
        prev = before.get(path)
        if prev is None or prev.sha256 != snap.sha256:
            changed.add(path)
            full_path = os.path.join(root, path.replace("/", os.sep))
            lines.append(f"diff --git a/{path} b/{path}")
            lines.append("new file mode 100644")
            lines.append("--- /dev/null")
            lines.append(f"+++ b/{path}")
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        for line in f.read().split("\n"):
                            lines.append("+" + line)
                except OSError:
                    pass

    # Deleted files.
    for path in before:
        if path not in after:
            changed.add(path)
            lines.append(f"diff --git a/{path} b/{path}")
            lines.append("deleted file mode 100644")
            lines.append(f"--- a/{path}")
            lines.append("+++ /dev/null")
            lines.append(f"@@ -1,{_line_count_of(root, path)} +0,0 @@")

    text = "\n".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    return DiffResult(unified_diff_text=text, files_changed=sorted(changed))


def _line_count_of(root: str, relative_path: str) -> int:
    full = os.path.join(root, relative_path.replace("/", os.sep))
    if not os.path.isfile(full):
        return 0
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return len(f.read().split("\n"))
    except OSError:
        return 0
