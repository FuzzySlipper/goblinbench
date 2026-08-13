#!/usr/bin/env python3
"""Materialize auditable CraftSurvive mutation worktrees for GoblinBench.

The benchmark never toggles a product flag or mutates the baseline checkout.
Each selected patch is applied to a detached worktree, committed as an
immutable local revision, checked with a narrow source contract, and paired
with a content-addressed proof record.  The generated worktree and proof path
are then supplied to one interactive-playtest cell through its scorer-side
environment variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "fixtures" / "interactive-playtest" / "mutations" / "manifest.json"


def run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def full_sha(value: str) -> str:
    value = value.strip().lower()
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"expected a full 40-character SHA, got {value!r}")
    return value


def clean_worktree(repo: Path) -> None:
    dirty = run_git(repo, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError(f"baseline repository is dirty: {dirty.splitlines()[:8]}")


def source_contract(mutation_id: str, worktree: Path) -> list[dict[str, Any]]:
    checks: list[tuple[str, Path, str]] = {
        "inverted-mouse-look": [
            ("horizontal pointer delta is inverted", worktree / "web/src/session-client.ts", "this.#look[0] -= event.movementX * 0.12;"),
        ],
        "world-axis-movement": [
            ("controller heading is fixed to world zero", worktree / "src/player.rs", "heading_yaw_radians: 0.0,"),
        ],
        "voxel-placement-offset": [
            ("placement address is shifted on X", worktree / "src/world.rs", "address[0] += 1;"),
        ],
        "visible-collision-traversal": [
            ("step height is disabled", worktree / "src/player.rs", "config.surface.maximum_step_height = 0.0;"),
        ],
    }.get(mutation_id, [])
    if not checks:
        raise ValueError(f"no source contract is registered for mutation {mutation_id!r}")
    result: list[dict[str, Any]] = []
    for label, path, needle in checks:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"source contract could not read {path}: {exc}") from exc
        passed = needle in content
        result.append({"label": label, "path": str(path), "needle": needle, "passed": passed})
        if not passed:
            raise ValueError(f"source contract failed for {mutation_id}: {label}")
    return result


def materialize(
    base_repo: Path,
    base_revision: str,
    mutation: dict[str, Any],
    output_root: Path,
    proof_root: Path,
) -> dict[str, Any]:
    mutation_id = str(mutation.get("id") or "").strip()
    patch_name = str(mutation.get("patch") or "").strip()
    patch_path = (MANIFEST_PATH.parent / patch_name).resolve()
    try:
        patch_path.relative_to(MANIFEST_PATH.parent.resolve())
    except ValueError as exc:
        raise ValueError(f"mutation patch escaped fixture root: {patch_name!r}") from exc
    if not patch_path.is_file():
        raise ValueError(f"mutation patch does not exist: {patch_path}")

    worktree = (output_root / mutation_id).resolve()
    if worktree.exists():
        raise ValueError(f"refusing to overwrite existing mutation worktree: {worktree}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    proof_root.mkdir(parents=True, exist_ok=True)

    run_git(base_repo, "worktree", "add", "--detach", str(worktree), base_revision)
    try:
        subprocess.run(
            ["git", "-C", str(worktree), "apply", "--check", str(patch_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(worktree), "apply", "--whitespace=nowarn", str(patch_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        changed = run_git(worktree, "diff", "--name-only").splitlines()
        if not changed:
            raise ValueError(f"mutation patch produced no changes: {mutation_id}")
        source_checks = source_contract(mutation_id, worktree)
        run_git(worktree, "add", "--", *changed)
        commit_env = os.environ.copy()
        commit_env.update({
            "GIT_AUTHOR_NAME": "GoblinBench mutation fixture",
            "GIT_AUTHOR_EMAIL": "goblinbench-fixtures@localhost",
            "GIT_COMMITTER_NAME": "GoblinBench mutation fixture",
            "GIT_COMMITTER_EMAIL": "goblinbench-fixtures@localhost",
        })
        subprocess.run(
            ["git", "-C", str(worktree), "commit", "-m", f"GoblinBench mutation: {mutation_id}"],
            check=True,
            capture_output=True,
            text=True,
            env=commit_env,
        )
        if run_git(worktree, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError(f"mutation worktree remained dirty after commit: {worktree}")
        revision = full_sha(run_git(worktree, "rev-parse", "HEAD"))
        patch_sha256 = hashlib.sha256(patch_path.read_bytes()).hexdigest()
        proof = {
            "schema_version": "goblinbench.interactive-playtest-mutation-proof/v1",
            "mutation_id": mutation_id,
            "cell_id": mutation.get("cell_id"),
            "defect_family": mutation.get("defect_family"),
            "base_revision": base_revision,
            "mutation_revision": revision,
            "worktree": str(worktree),
            "patch": str(patch_path),
            "patch_sha256": patch_sha256,
            "source_checks": source_checks,
            "proof_text": mutation.get("proof"),
            "worktree_clean": True,
            "product_smoke": "pending: run the CraftSurvive browser smoke on this exact worktree and append its retained artifact path",
        }
        proof_path = proof_root / f"{mutation_id}-{revision}.json"
        proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "mutation_id": mutation_id,
            "cell_id": mutation.get("cell_id"),
            "defect_family": mutation.get("defect_family"),
            "base_revision": base_revision,
            "mutation_revision": revision,
            "worktree": str(worktree),
            "mutation_proof_path": str(proof_path),
            "mutation_proof": str(mutation.get("proof") or ""),
            "patch_sha256": patch_sha256,
        }
    except Exception:
        # Leave a failed worktree in place for inspection.  It is never passed
        # to GoblinBench because no result record is emitted on failure.
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, help="clean CraftSurvive checkout")
    parser.add_argument("--base-revision", required=True, help="full SHA checked out by the baseline")
    parser.add_argument("--output-root", required=True, help="durable root for detached mutation worktrees")
    parser.add_argument(
        "--proof-root",
        default=str(REPO_ROOT / "docs" / "evidence" / "interactive-playtest" / "mutations"),
        help="durable root for generated mutation proof JSON",
    )
    parser.add_argument("--mutation", action="append", dest="mutations", help="mutation id (repeatable; default all)")
    args = parser.parse_args(argv)

    try:
        base_repo = Path(args.repo_root).expanduser().resolve()
        if not base_repo.is_dir():
            raise ValueError(f"CraftSurvive repository does not exist: {base_repo}")
        base_revision = full_sha(args.base_revision)
        actual = full_sha(run_git(base_repo, "rev-parse", "HEAD"))
        if actual != base_revision:
            raise ValueError(f"baseline revision mismatch: requested {base_revision}, repository HEAD is {actual}")
        clean_worktree(base_repo)
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        mutations = manifest.get("mutations") if isinstance(manifest, dict) else None
        if not isinstance(mutations, list):
            raise ValueError("mutation manifest has no mutations list")
        requested = set(args.mutations or [str(item.get("id")) for item in mutations if isinstance(item, dict)])
        selected = [item for item in mutations if isinstance(item, dict) and str(item.get("id")) in requested]
        unknown = requested - {str(item.get("id")) for item in mutations if isinstance(item, dict)}
        if unknown:
            raise ValueError(f"unknown mutation ids: {sorted(unknown)}")
        results = [
            materialize(base_repo, base_revision, item, Path(args.output_root).expanduser().resolve(), Path(args.proof_root).expanduser().resolve())
            for item in selected
        ]
        print(json.dumps({"schema_version": "goblinbench.interactive-playtest-mutation-set/v1", "base_revision": base_revision, "mutations": results}, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"prepare-playtest-mutations: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
