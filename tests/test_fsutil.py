from __future__ import annotations

import importlib.util
import pathlib
import stat
import sys


REPO = pathlib.Path(__file__).resolve().parents[1]
FSUTIL_PATH = REPO / "scripts/gb/fsutil.py"


def load_fsutil():
    spec = importlib.util.spec_from_file_location("goblinbench_fsutil", FSUTIL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_copy_directory_preserves_executable_fixture_scripts(tmp_path: pathlib.Path) -> None:
    fsutil = load_fsutil()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    script = source / "harness/ci/check.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\nexit 0\n")
    script.chmod(0o755)

    fsutil.copy_directory(str(source), str(destination), set())

    copied_mode = (destination / "harness/ci/check.sh").stat().st_mode
    assert copied_mode & stat.S_IXUSR
