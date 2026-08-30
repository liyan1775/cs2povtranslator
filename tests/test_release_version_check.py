from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release_version.py"


def _run(tag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag, "--root", str(ROOT)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def test_release_check_accepts_tag_matching_package_version() -> None:
    result = _run("v0.9.8")

    assert result.returncode == 0, result.stderr
    assert "0.9.8" in result.stdout


def test_release_check_rejects_mismatched_tag() -> None:
    result = _run("v9.9.9")

    assert result.returncode == 1
    assert "v9.9.9" in result.stdout
    assert "0.9.8" in result.stdout
