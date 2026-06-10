from __future__ import annotations

import json
from pathlib import Path

from cs2pov.cli.job_ops import export_job, inspect_job, resolve_job_dir
from cs2pov.domain.models import PipelineConfig, StageName, StageStatus, TranscriptSegment, TranslationSegment, VoiceActivityCue
from cs2pov.pipeline.manifest import PipelineManifest
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_json, write_jsonl


def _make_job(tmp_path: Path) -> ArtifactStore:
    store = ArtifactStore(tmp_path / "output" / "20260610_de_mirage")
    store.ensure_dirs()
    cfg = PipelineConfig(selected_team_number=2, export_scope="pov_team", subtitle_bilingual_format="label", whisper_model="tiny", transcription_mode="round", llm_model="deepseek-v4-flash")
    manifest = PipelineManifest.create(store.job_dir.name, cfg)
    for stage in StageName:
        manifest.set_stage(stage, StageStatus.COMPLETED)
    manifest.save(store.manifest_path)
    write_json(store.demo_info_path, {"map_name": "de_mirage", "server_name": "FACEIT"})
    write_json(store.rounds_path, [{"round_number": 1, "start_time": 0.0, "end_time": 10.0}])
    write_json(store.transcription_coverage_path, {"longest_transcript_segment_seconds": 3.0})
    write_json(store.voice_manifest_path, {"players": [{"steamid": "s1", "name": "p1", "team_number": 2}]})
    write_jsonl(store.transcripts_path, [TranscriptSegment("seg1", "s1", "p1", 2, 1.0, 2.0, "one bench", round_number=1)])
    write_jsonl(store.translations_path, [TranslationSegment("seg1", "s1", "p1", 2, 1.0, 2.0, "one bench", "长椅一个", round_number=1)])
    write_jsonl(store.voice_activity_path, [VoiceActivityCue("v1", "s1", "p1", 2, 1.0, 2.0, 3)])
    return store


def test_resolve_job_dir_chooses_latest_job(tmp_path: Path):
    old = _make_job(tmp_path)
    latest = ArtifactStore(tmp_path / "output" / "20260611_de_dust2")
    latest.ensure_dirs()
    (latest.job_dir / "manifest.json").write_text("{}", encoding="utf-8")
    assert resolve_job_dir(tmp_path / "output") == latest.job_dir.resolve()


def test_inspect_job_reports_counts_without_leaking_secret(tmp_path: Path):
    store = _make_job(tmp_path)
    summary = inspect_job(store.job_dir)
    raw = json.dumps(summary, ensure_ascii=False)
    assert summary["map_name"] == "de_mirage"
    assert summary["transcript_segments"] == 1
    assert summary["translation_segments"] == 1
    assert summary["has_secret_leak"] is False
    assert "sk-" not in raw


def test_export_job_can_generate_zh_only_final_srt(tmp_path: Path):
    store = _make_job(tmp_path)
    outputs = export_job(store.job_dir, fmt="zh")
    zh_path = Path(outputs["zh_srt"])
    assert zh_path.exists()
    assert zh_path.name == "team_2.zh.srt"
    assert "长椅一个" in zh_path.read_text(encoding="utf-8")
