from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from cs2pov.application.workspace_runtime import WorkspaceRuntime
from cs2pov.cli import commands, wizard
from cs2pov.cli.job_ops import resolve_job_dir
from cs2pov.services.comms_service import CommsRenderOptions, CommsService


def _runtime(tmp_path: Path) -> WorkspaceRuntime:
    return WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1)


def test_read_default_job_root_comes_from_selected_workspace(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(commands, "_resolve_read_runtime", lambda: runtime)

    assert commands._resolve_job_argument(None, write=False) == runtime.paths.jobs_dir


def test_explicit_read_job_path_does_not_require_workspace(tmp_path):
    legacy = tmp_path / "legacy-job"
    legacy.mkdir()
    (legacy / "manifest.json").write_text(json.dumps({"config": {}}), encoding="utf-8")

    assert resolve_job_dir(legacy) == legacy.resolve()


def test_write_job_argument_resolves_write_runtime_before_job_lookup(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    calls: list[str] = []

    def resolve():
        calls.append("write")
        return runtime

    monkeypatch.setattr(commands, "_resolve_write_runtime", resolve)

    args = argparse.Namespace(
        cmd="export", path=None, format="zh", team_number=None, pov_steamid=None,
        export_scope=None, bilingual_format=None, preset=None, overlap_policy=None,
        max_duration=None, min_duration=None,
    )
    monkeypatch.setattr(commands, "export_job", lambda *a, **k: calls.append("lookup") or {})

    assert commands.dispatch(args, argparse.ArgumentParser()) == 0
    assert calls[:2] == ["write", "lookup"]


def test_wizard_help_has_no_output_option(capsys):
    with pytest.raises(SystemExit):
        wizard.main(["--help"])
    assert "--output" not in capsys.readouterr().out


def test_comms_render_uses_explicit_runtime_temp_root_and_cleans_it(tmp_path, monkeypatch):
    store = type("Store", (), {"job_dir": tmp_path / "job", "review_dir": tmp_path / "job" / "review", "final_dir": tmp_path / "job" / "final", "ensure_dirs": lambda self: None})()
    store.review_dir.mkdir(parents=True)
    store.final_dir.mkdir(parents=True)
    (store.review_dir / "comms_rounds").mkdir()
    (store.review_dir / "comms_rounds" / "round_01.yaml").write_text(
        "round: 1\nduration_seconds: 1\nmessages: []\n", encoding="utf-8"
    )
    temp_root = tmp_path / "workspace" / "cache" / "tmp"
    seen: list[Path | None] = []

    def fake_render(*args, **kwargs):
        seen.append(kwargs.get("temp_root"))
        return tmp_path / "job" / "final" / "out.png"

    monkeypatch.setattr("cs2pov.services.comms_service._render_round_video", fake_render)
    # No ffmpeg/Pillow is needed: the boundary call itself must carry the root.
    CommsService().render(store, formats=["preview"], options=CommsRenderOptions(), temp_root=temp_root)
    assert seen and seen[0] is not None
    assert temp_root.exists()
    assert not any(temp_root.iterdir())
