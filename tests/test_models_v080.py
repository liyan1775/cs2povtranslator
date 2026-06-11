from pathlib import Path

from cs2pov.cli.model_manager import (
    TRANSCRIPTION_PROFILES,
    format_bytes,
    profile_to_config,
    scan_downloaded_models,
)


def test_quality_profile_maps_to_small_cpu_int8():
    cfg = profile_to_config("quality")
    assert cfg["whisper_model"] == "small"
    assert cfg["whisper_device"] == "cpu"
    assert cfg["whisper_compute_type"] == "int8"
    assert "quality" in TRANSCRIPTION_PROFILES


def test_format_bytes_human_readable():
    assert format_bytes(1024 * 1024).endswith("MB")


def test_scan_downloaded_models_detects_hf_cache(monkeypatch, tmp_path):
    hub = tmp_path / "hub"
    model = hub / "models--Systran--faster-whisper-small"
    model.mkdir(parents=True)
    (model / "dummy.bin").write_bytes(b"12345")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    rows = scan_downloaded_models()
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
