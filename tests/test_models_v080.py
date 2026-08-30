from pathlib import Path
import tempfile
import shutil

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
    runtime = _runtime(tmp_path)
    whisper = runtime.paths.whisper_cache_dir
    hub = runtime.paths.huggingface_hub_cache_dir
    for root in (whisper, hub):
        model = root / "models--Systran--faster-whisper-small"
        model.mkdir(parents=True)
        (model / "x").write_bytes(b"x")
    external = Path(tempfile.mkdtemp(prefix="legacy-cache-"))
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
    shutil.rmtree(external)


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
