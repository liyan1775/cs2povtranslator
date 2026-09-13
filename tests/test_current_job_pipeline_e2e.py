from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_current_job_pipeline_e2e_uses_independent_processes():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_current_job_pipeline_e2e.py")],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, {"stdout": result.stdout, "stderr": result.stderr}
    assert "independent create/reopen/resume/subtitle export processes" in result.stdout


def test_e2e_script_declares_only_supported_fixture_boundaries():
    source = (Path(__file__).resolve().parents[1] / "scripts/check_current_job_pipeline_e2e.py").read_text(encoding="utf-8")
    assert "FakeParser" in source and "FakeExtractor" in source and "FakeASR" in source and "FakeProvider" in source
    assert "CurrentJobSubtitleApplicationService" in source
    assert "--child" in source
