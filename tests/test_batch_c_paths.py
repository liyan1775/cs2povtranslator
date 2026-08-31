from __future__ import annotations

import argparse
import json
import os
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
    monkeypatch.setattr(commands, "export_job", lambda *a, **k: calls.extend(["lookup", k["runtime"]]) or {})

    assert commands.dispatch(args, argparse.ArgumentParser()) == 0
    assert calls[:2] == ["write", "lookup"]
    assert calls[2] is runtime


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
    CommsService().render(store, formats=["preview"], options=CommsRenderOptions(), temp_root=temp_root, runtime=_runtime(tmp_path))
    assert seen and seen[0] is not None
    assert temp_root.exists()
    assert not any(temp_root.iterdir())


def test_direct_export_write_gate_rejects_before_job_lookup(tmp_path, monkeypatch):
    from cs2pov.cli import job_ops

    def fail_lookup(path):
        raise AssertionError("job lookup must not run before write gate")

    monkeypatch.setattr(job_ops, "_require_job", fail_lookup)
    monkeypatch.setattr(job_ops.WorkspaceRuntimeResolver, "resolve_for_write", lambda self: (_ for _ in ()).throw(job_ops.WorkspaceRuntimeError("workspace_selection_required", "未选择", "先选择")))
    with pytest.raises(job_ops.WorkspaceRuntimeError) as caught:
        job_ops.export_job(tmp_path / "old-job")
    assert caught.value.code == "workspace_selection_required"


@pytest.mark.parametrize("entry", ["retranslate", "feedback"])
def test_direct_write_entries_gate_before_job_lookup(tmp_path, monkeypatch, entry):
    from cs2pov.cli import job_ops, commands

    monkeypatch.setattr(job_ops, "_require_job", lambda path: (_ for _ in ()).throw(AssertionError("lookup before gate")))
    error = job_ops.WorkspaceRuntimeError("workspace_selection_required", "未选择", "先选择")
    monkeypatch.setattr(job_ops.WorkspaceRuntimeResolver, "resolve_for_write", lambda self: (_ for _ in ()).throw(error))
    with pytest.raises(job_ops.WorkspaceRuntimeError):
        (job_ops.retranslate_job if entry == "retranslate" else commands.run_feedback)(tmp_path / "old-job")


def test_direct_clean_delete_gates_before_inspecting_path(tmp_path, monkeypatch):
    from cs2pov.cli import commands
    from cs2pov.application.workspace_runtime import WorkspaceRuntimeError

    error = WorkspaceRuntimeError("workspace_selection_required", "未选择", "先选择")
    monkeypatch.setattr(commands, "resolve_write_runtime", lambda runtime=None: (_ for _ in ()).throw(error))
    with pytest.raises(WorkspaceRuntimeError):
        commands.run_clean(tmp_path / "missing", delete=True)


def test_launcher_empty_job_path_reports_workspace_error_without_fake_path(monkeypatch):
    from cs2pov.cli import launcher
    from cs2pov.application.workspace_runtime import WorkspaceRuntimeError

    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setattr(launcher, "WorkspaceRuntimeResolver", lambda *a, **k: type("R", (), {"resolve_for_read": lambda self: (_ for _ in ()).throw(WorkspaceRuntimeError("workspace_selection_required", "未选择", "先选择"))})())
    with pytest.raises(launcher.ReturnToMainMenu):
        launcher.ask_job_path()


def test_launcher_write_menu_workspace_error_has_stable_message(monkeypatch, capsys):
    from cs2pov.cli import launcher
    from cs2pov.application.workspace_runtime import WorkspaceRuntimeError

    monkeypatch.setattr(launcher, "print_banner", lambda: None)
    monkeypatch.setattr(launcher, "print_menu", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt: "6")
    monkeypatch.setattr(launcher, "run_tools_menu", lambda: (_ for _ in ()).throw(
        WorkspaceRuntimeError("workspace_unhealthy", "工作区不可写", "请修复工作区")
    ))

    assert launcher.main(["--once"]) == 0
    output = capsys.readouterr().out
    assert "错误[workspace_unhealthy]：工作区不可写" in output
    assert "建议：请修复工作区" in output
    assert "操作失败：WorkspaceRuntimeError" not in output


def _benchmark_args(output: str | None, *, cache_dir: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        demo="demo.dem", output=output, models="tiny", team_number=None, max_rounds=1,
        device=None, compute_type=None, language="auto", cache_dir=cache_dir, json=False,
    )


@pytest.mark.parametrize("output", ["", "bad\x00path"])
def test_benchmark_invalid_explicit_output_is_stable_and_does_not_write(tmp_path, monkeypatch, output):
    from cs2pov.application.job_runtime import JobRuntimeError

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cs2pov.storage.jsonl.write_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("report write")))
    with pytest.raises(JobRuntimeError) as caught:
        commands.run_asr_benchmark(_benchmark_args(output), runtime=_runtime(tmp_path))
    assert caught.value.code == "job_path_escape"
    assert list(tmp_path.iterdir()) == []


def test_empty_deprecated_cache_overrides_are_rejected_without_writes(tmp_path, monkeypatch, capsys):
    from cs2pov.application.job_runtime import JobRuntimeError

    monkeypatch.setattr(commands, "test_model_load", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("model load")))
    monkeypatch.setattr("cs2pov.application.workspace_runtime.WorkspaceRuntimeResolver", lambda *args, **kwargs: type("R", (), {
        "resolve_for_write": lambda self: _runtime(tmp_path),
        "resolve_selected": lambda self: _runtime(tmp_path),
    })())
    assert commands.main(["models", "test", "--cache-dir", "", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "legacy_model_cache_override_rejected"

    with pytest.raises(JobRuntimeError) as caught:
        commands.run_asr_benchmark(_benchmark_args(None, cache_dir=""), runtime=_runtime(tmp_path))
    assert caught.value.code == "legacy_model_cache_override_rejected"

    monkeypatch.setattr(commands, "save_config", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("config write")))
    assert commands.main(["config", "set", "--whisper-cache-dir", ""]) == 1
    assert "模型缓存跟随当前工作区" in capsys.readouterr().out


def test_comms_render_passes_runtime_env_and_cleans_on_ffmpeg_failure(tmp_path, monkeypatch):
    from cs2pov.services import comms_service

    store = type("Store", (), {"job_dir": tmp_path / "job", "review_dir": tmp_path / "job" / "review", "final_dir": tmp_path / "job" / "final", "ensure_dirs": lambda self: None})()
    (store.review_dir / "comms_rounds").mkdir(parents=True)
    store.final_dir.mkdir(parents=True)
    (store.review_dir / "comms_rounds" / "round_01.yaml").write_text("round: 1\nduration_seconds: 1\nmessages: []\n", encoding="utf-8")
    temp_root = tmp_path / "workspace" / "cache" / "tmp"
    captured = {}
    monkeypatch.setattr(comms_service.shutil, "which", lambda _: "ffmpeg.exe")
    monkeypatch.setattr(comms_service, "_draw_overlay_state", lambda *args, **kwargs: None)
    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        raise RuntimeError("ffmpeg failed")
    monkeypatch.setattr(comms_service.subprocess, "run", fake_run)
    before = dict(os.environ)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        CommsService().render(store, formats=["preview"], options=CommsRenderOptions(), temp_root=temp_root, runtime=_runtime(tmp_path), subprocess_env={"HF_HOME": "runtime-hf"})
    assert os.environ == before
    assert captured["env"]["HF_HOME"] == "runtime-hf"
    assert Path(captured["env"]["TMP"]).is_relative_to(temp_root)
    assert Path(captured["env"]["TEMP"]) == Path(captured["env"]["TMP"])
    assert Path(captured["env"]["TMPDIR"]) == Path(captured["env"]["TMP"])
    assert not any(temp_root.iterdir())
