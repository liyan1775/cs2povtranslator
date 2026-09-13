from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_current_job_output_matches_legacy_golden_semantics_and_srt():
    result = subprocess.run(
        [sys.executable, "scripts/check_current_job_output_equivalence.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "canonical rows and v0.9.8 bilingual SRT" in result.stdout
