from __future__ import annotations

import json
from pathlib import Path

from cs2pov.cli.output_explainer import build_output_explanation, print_output_explanation
from cs2pov.cli.setup_check import build_setup_report, print_setup_report
from cs2pov.domain.models import PipelineConfig, StageName, StageStatus, TranscriptSegment, TranslationSegment, VoiceActivityCue
from cs2pov.pipeline.manifest import PipelineManifest
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_json, write_jsonl


def _make_job(tmp_path: Path) -> ArtifactStore:
    store = ArtifactStore(tmp_path / "output" / "20260610_de_mirage")
    store.ensure_dirs()
    cfg = PipelineConfig(selected_team_number=2, export_scope="pov_team", whisper_model="tiny", transcription_mode="round", llm_model="deepseek-v4-flash")
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
    (store.final_dir / "team_2.bilingual.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n[p1] one bench\n[中文] 长椅一个\n", encoding="utf-8")
    (store.final_dir / "team_2.zh.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n[p1] 长椅一个\n", encoding="utf-8")
    (store.review_dir / "team_2.original.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n[p1] one bench\n", encoding="utf-8")
    return store


def test_setup_check_report_is_json_serializable(tmp_path: Path):
    report = build_setup_report(tmp_path)
    text = json.dumps(report, ensure_ascii=False)
    assert "modules" in report
    assert "sk-" not in text
    assert "ready_for_dry_run" in report


def test_print_setup_report_has_user_next_step(tmp_path: Path, capsys):
    code = print_setup_report(build_setup_report(tmp_path))
    out = capsys.readouterr().out
    assert code in {0, 1}
    assert "启动前检查" in out
    assert "结论" in out


def test_explain_output_points_to_final_files(tmp_path: Path, capsys):
    store = _make_job(tmp_path)
    report = build_output_explanation(store.job_dir)
    print_output_explanation(report)
    out = capsys.readouterr().out
    assert "输出文件说明" in out
    assert "final/team_2.bilingual.srt" in out
    assert "推荐导入剪映" in out
    assert "artifacts/transcript_segments.jsonl" in out


def test_output_explainer_normalizes_windows_paths():
    from cs2pov.cli.output_explainer import _normalize_relative_paths

    paths = [r"final\team_2.bilingual.srt", r"review\team_2.original.srt", "debug/team_2.voice_activity.srt"]
    assert _normalize_relative_paths(paths) == [
        "final/team_2.bilingual.srt",
        "review/team_2.original.srt",
        "debug/team_2.voice_activity.srt",
    ]
