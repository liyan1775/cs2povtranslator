from pathlib import Path

import pytest

from cs2pov.cli.model_manager import (
    TRANSCRIPTION_PROFILES,
    format_bytes,
    profile_to_config,
    scan_downloaded_models,
)
from cs2pov.application.workspace_runtime import WorkspaceRuntime


def _runtime(tmp_path):
    return WorkspaceRuntime(tmp_path, "id", 1, 1)


def test_workspace_scan_is_explicit_and_separates_legacy(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path / "workspace")
    whisper = runtime.paths.whisper_cache_dir
    hub = runtime.paths.huggingface_hub_cache_dir
    for root in (whisper, hub):
        model = root / "models--Systran--faster-whisper-small"
        model.mkdir(parents=True)
        (model / "x").write_bytes(b"x")
    external = tmp_path / "external"
    monkeypatch.setenv("HF_HUB_CACHE", str(external))
    from cs2pov.cli import model_manager
    current = model_manager.scan_current_models(runtime)
    assert {row["name"] for row in current} == {"small"}
    assert all(row["managed"] is True for row in current)
    assert all("source" in row for row in current)
    (external / "models--Systran--faster-whisper-base").mkdir(parents=True)
    legacy = model_manager.scan_legacy_candidates(
        configured_cache=external, hf_home=external / "home", hf_hub_cache=external,
        runtime=runtime,
    )
    assert any(row["source"] == "configured" for row in legacy)
    assert any(row["managed"] is False for row in legacy)
    assert any(row["name"] == "base" for row in model_manager.scan_legacy_models(legacy))


def test_model_load_requires_explicit_cache_and_passes_download_root(monkeypatch, tmp_path):
    from cs2pov.cli import model_manager
    captured = {}
    class Fake:
        def __init__(self, model, **kwargs): captured.update(kwargs)
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", type("M", (), {"WhisperModel": Fake}))
    result = model_manager.test_model_load("small", "cpu", "int8")
    assert result["ok"] is False and result["code"] == "model_cache_required"
    result = model_manager.test_model_load("small", "cpu", "int8", cache_dir=str(tmp_path))
    assert result["ok"] is True and captured["download_root"] == str(tmp_path)


def test_invalid_state_path_is_structured_json(monkeypatch, capsys):
    from cs2pov.cli.commands import main
    monkeypatch.setenv("CS2POV_STATE_FILE", "relative-state.json")
    assert main(["models", "info", "--json"]) == 1
    assert '"code": "selection_state_location_unavailable"' in capsys.readouterr().out


def test_model_override_non_json_is_user_readable(monkeypatch, tmp_path, capsys):
    from argparse import Namespace
    from cs2pov.cli import commands
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(commands, "load_config", lambda: {"whisper_model": "base", "whisper_device": "cpu", "whisper_compute_type": "int8"})
    import cs2pov.application.workspace_runtime as runtime_module
    monkeypatch.setattr(runtime_module, "WorkspaceRuntimeResolver", lambda *a, **k: type("R", (), {"resolve_for_write": lambda s: runtime})())
    args = Namespace(models_cmd="test", cache_dir=str(tmp_path / "out"), model=None, profile=None, device=None, compute_type=None, local_only=False, json=False)
    assert commands.run_models(args, __import__("argparse").ArgumentParser()) == 1
    output = capsys.readouterr().out
    assert "None:" not in output and "{" not in output
    assert "已弃用" in output


def test_deprecated_set_cache_and_config_cache_are_zero_write(monkeypatch, tmp_path, capsys):
    from cs2pov.cli.commands import main
    import cs2pov.storage.config_store as store
    config = tmp_path / "config.json"
    config.write_text('{"llm_model":"OLD"}\n', encoding="utf-8")
    monkeypatch.setattr(store, "CONFIG_PATH", config)
    monkeypatch.setattr(store, "CONFIG_DIR", tmp_path)
    out = tmp_path / "out"
    assert main(["models", "set-cache", str(out)]) == 1
    assert not out.exists()
    before = config.read_bytes()
    assert main(["config", "set", "--model", "NEW", "--whisper-cache-dir", str(out)]) == 1
    assert config.read_bytes() == before and not out.exists()


def test_current_scanner_requires_runtime_and_deduplicates_by_priority(tmp_path):
    from cs2pov.cli import model_manager
    with pytest.raises(TypeError): model_manager.cache_candidates()
    with pytest.raises(TypeError): model_manager.scan_downloaded_models()
    runtime = _runtime(tmp_path)
    for root, name in ((runtime.paths.whisper_cache_dir, "small"), (runtime.paths.huggingface_hub_cache_dir, "small"), (runtime.paths.huggingface_hub_cache_dir, "base")):
        folder = root / f"models--x--faster-whisper-{name}"
        folder.mkdir(parents=True)
        (folder / "x").write_bytes(b"1")
    rows = model_manager.scan_current_models(runtime)
    assert [(r["name"], r["source"]) for r in rows] == [("small", "workspace_whisper"), ("base", "workspace_huggingface_hub")]


def test_legacy_runtime_inputs_are_explicit_deduplicated_and_read_only(tmp_path):
    from cs2pov.cli import model_manager

    runtime = _runtime(tmp_path / "workspace")
    configured = tmp_path / "configured"
    configured_hub = configured / "hub"
    hf_home_hub = tmp_path / "hf-home" / "hub"
    hf_hub = tmp_path / "hf-hub"
    default_hub = tmp_path / "isolated-home" / ".cache" / "huggingface" / "hub"
    for path in (configured, configured_hub, hf_home_hub, hf_hub, default_hub):
        path.mkdir(parents=True)
    missing = tmp_path / "missing"

    rows = model_manager._legacy_candidates_for_runtime(
        runtime,
        config={"whisper_cache_dir": str(configured)},
        environ={"HF_HOME": str(hf_home_hub.parent), "HF_HUB_CACHE": str(hf_hub)},
        home=tmp_path / "isolated-home",
    )

    assert [(row["source"], Path(row["path"])) for row in rows] == [
        ("configured", configured.resolve()),
        ("configured", configured_hub.resolve()),
        ("HF_HOME", hf_home_hub.resolve()),
        ("HF_HUB_CACHE", hf_hub.resolve()),
        ("platform_default", default_hub.resolve()),
    ]
    assert all(row["managed"] is False for row in rows)
    assert not missing.exists()

    excluded = model_manager._legacy_candidates_for_runtime(
        runtime,
        config={"whisper_cache_dir": str(runtime.root)},
        environ={"HF_HOME": str(runtime.root), "HF_HUB_CACHE": str(runtime.paths.whisper_cache_dir)},
        home=runtime.root,
    )
    assert excluded == []


def test_text_model_list_shows_legacy_models_when_current_cache_is_empty(tmp_path, capsys):
    from cs2pov.cli import model_manager

    runtime = _runtime(tmp_path / "workspace")
    legacy = tmp_path / "legacy"
    model = legacy / "models--Systran--faster-whisper-base"
    model.mkdir(parents=True)
    (model / "model.bin").write_bytes(b"legacy")

    result = model_manager.print_models_list(
        runtime,
        json_mode=False,
        config={"whisper_cache_dir": str(legacy)},
        environ={},
        home=tmp_path / "isolated-home",
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "当前工作区没有发现" in output
    assert "旧缓存模型" in output
    assert "base" in output
    assert str(model) in output


def test_quality_profile_maps_to_small_cpu_int8():
    cfg = profile_to_config("quality")
    assert cfg["whisper_model"] == "small"
    assert cfg["whisper_device"] == "cpu"
    assert cfg["whisper_compute_type"] == "int8"
    assert "quality" in TRANSCRIPTION_PROFILES


def test_format_bytes_human_readable():
    assert format_bytes(1024 * 1024).endswith("MB")


def test_scan_downloaded_models_detects_hf_cache(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    hub = runtime.paths.huggingface_hub_cache_dir
    model = hub / "models--Systran--faster-whisper-small"
    model.mkdir(parents=True)
    (model / "dummy.bin").write_bytes(b"12345")
    rows = scan_downloaded_models(runtime)
    assert any(row["name"] == "small" and row["size_bytes"] == 5 for row in rows)


def test_benchmark_report_uses_demo_basename(monkeypatch, tmp_path):
    from argparse import Namespace
    import cs2pov.cli.commands as commands

    class DummyStore:
        def __init__(self, job_dir):
            self.job_dir = job_dir
            self.transcription_coverage_path = job_dir / "artifacts" / "transcription_coverage.json"

    class DummyEngine:
        def __init__(self, config):
            self.config = config
            self.store = DummyStore(Path(config.output_root) / "20260101_000000_de_mirage")

        def run(self, demo):
            self.store.transcription_coverage_path.parent.mkdir(parents=True, exist_ok=True)
            self.store.transcription_coverage_path.write_text('{"postprocessed_transcript_segments": 1}', encoding="utf-8")

    monkeypatch.setattr(commands, "PipelineEngine", DummyEngine)
    monkeypatch.chdir(tmp_path)
    args = Namespace(
        demo="D:\\agent_workspace\\cs2demos\\match.dem.zst",
        output="bench_out",
        models="base",
        team_number=2,
        max_rounds=1,
        device="cpu",
        compute_type="int8",
        language="auto",
        cache_dir=None,
        json=False,
    )
    assert commands.run_asr_benchmark(args) == 0
    report = (tmp_path / "bench_out" / "asr_benchmark.json").read_text(encoding="utf-8")
    assert "agent_workspace" not in report
    assert "D:" not in report
    assert "match.dem.zst" in report
