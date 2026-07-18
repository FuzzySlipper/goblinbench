#!/usr/bin/env python3
"""Small fixture-owned dependency verifier modeled on ASHA ownership cells."""

from __future__ import annotations

import json
import pathlib
import re
import sys
import tomllib


ROOT = pathlib.Path(__file__).resolve().parents[1]
OWNERSHIP = tomllib.loads((ROOT / "governance/ownership.toml").read_text())


def rust_failures() -> list[str]:
    failures: list[str] = []
    crates = OWNERSHIP.get("crate", {})
    names: dict[str, str] = {}
    manifests: dict[str, dict] = {}
    for manifest in sorted((ROOT / "crates").glob("*/Cargo.toml")):
        data = tomllib.loads(manifest.read_text())
        key = manifest.parent.relative_to(ROOT).as_posix()
        name = data["package"]["name"]
        names[name] = key
        manifests[key] = data
        if key not in crates:
            failures.append(f"{key} has no ownership entry")

    for key, data in manifests.items():
        allowed = set(crates.get(key, {}).get("may_depend_on", []))
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            for dependency, spec in data.get(section, {}).items():
                package = spec.get("package", dependency) if isinstance(spec, dict) else dependency
                if package in names and package not in allowed:
                    failures.append(f"{key} imports unlisted Rust crate {package}")
    return failures


def package_imports(source_root: pathlib.Path) -> set[str]:
    imports: set[str] = set()
    pattern = re.compile(r'["\'](@mini-asha/[a-z0-9-]+)(/[^"\']*)?["\']')
    for source in source_root.rglob("*.ts"):
        for match in pattern.finditer(source.read_text()):
            package, suffix = match.groups()
            imports.add(package + (suffix or ""))
    return imports


def typescript_failures() -> list[str]:
    failures: list[str] = []
    packages = OWNERSHIP.get("package", {})
    for package_dir in sorted((ROOT / "ts/packages").iterdir()):
        if not package_dir.is_dir():
            continue
        key = package_dir.relative_to(ROOT).as_posix()
        manifest_path = package_dir / "package.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        package_name = manifest.get("name")
        if key not in packages:
            failures.append(f"{key} has no ownership entry")
            continue
        if "." not in manifest.get("exports", {}):
            failures.append(f"{package_name} has no root export")
        if not (package_dir / "src/index.ts").exists():
            failures.append(f"{package_name} has no src/index.ts root barrel")

        allowed = set(packages[key].get("may_import", []))
        imports = package_imports(package_dir / "src")
        for imported in sorted(imports):
            root = "/".join(imported.split("/")[:2])
            if imported != root:
                failures.append(f"{package_name} uses forbidden deep import {imported}")
            if root != package_name and root not in allowed:
                failures.append(f"{package_name} imports unlisted package {root}")

        declared = set()
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            declared.update(name for name in manifest.get(section, {}) if name.startswith("@mini-asha/"))
        for dependency in sorted(declared - allowed):
            failures.append(f"{package_name} declares unlisted package {dependency}")
    return failures


def main() -> int:
    failures = rust_failures() + typescript_failures()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("ownership and dependency boundaries: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

