from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_round_orchestration_checker_replays_real_child_processes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_round_orchestration.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "round orchestration replay passed"
    assert result.stderr == ""
