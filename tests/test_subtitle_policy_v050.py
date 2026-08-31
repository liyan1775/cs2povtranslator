from pathlib import Path

from cs2pov.cli.job_ops import export_job
from cs2pov.application.workspace_runtime import WorkspaceRuntime
from cs2pov.domain.models import PipelineConfig, StageName, StageStatus, TranscriptSegment, TranslationSegment, VoiceActivityCue
from cs2pov.domain.subtitle import SubtitlePolicy, apply_subtitle_policy, policy_from_preset
from cs2pov.pipeline.manifest import PipelineManifest
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_json, write_jsonl


def test_editing_policy_shifts_overlapping_cues():
    first = TranslationSegment("a", "s1", "p1", 2, 1.0, 4.0, "one", "一个", round_number=1)
    second = TranslationSegment("b", "s2", "p2", 2, 2.0, 3.0, "two", "两个", round_number=1)
    policy = SubtitlePolicy(name="editing", overlap_policy="shift", max_duration_seconds=7.0, min_gap_seconds=0.1)
    out = apply_subtitle_policy([first, second], policy)
    assert out[1].start_time >= out[0].end_time + 0.09


def test_compact_policy_caps_duration():
    seg = TranslationSegment("a", "s1", "p1", 2, 1.0, 20.0, "long", "很长", round_number=1)
    out = apply_subtitle_policy([seg], policy_from_preset("compact"))
    assert out[0].end_time - out[0].start_time <= 5.0


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


def test_export_editing_preset_generates_compact_and_zh(tmp_path: Path):
    store = _make_job(tmp_path)
    outputs = export_job(store.job_dir, preset="editing", runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))
    assert "compact_srt" in outputs
    assert "zh_srt" in outputs
    assert Path(outputs["compact_srt"]).exists()
    assert "长椅一个" in Path(outputs["compact_srt"]).read_text(encoding="utf-8")


def test_export_debug_format_contains_round_and_team(tmp_path: Path):
    store = _make_job(tmp_path)
    outputs = export_job(store.job_dir, fmt="debug", runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))
    text = Path(outputs["debug_srt"]).read_text(encoding="utf-8")
    assert "[R1][T2][p1]" in text


def test_export_zh_clean_omits_player_name(tmp_path: Path):
    store = _make_job(tmp_path)
    outputs = export_job(store.job_dir, fmt="zh_clean", runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))
    text = Path(outputs["zh_clean_srt"]).read_text(encoding="utf-8")
    assert "长椅一个" in text
    assert "[p1]" not in text


def test_default_subtitle_config_is_bilingual_editing_first():
    from cs2pov.domain.models import PipelineConfig
    from cs2pov.storage.config_store import DEFAULT_CONFIG

    cfg = PipelineConfig()
    assert cfg.subtitle_export_preset == "editing"
    assert cfg.subtitle_overlap_policy == "stack"
    assert DEFAULT_CONFIG["subtitle_export_preset"] == "editing"
    assert DEFAULT_CONFIG["subtitle_overlap_policy"] == "stack"


def test_editing_preset_keeps_bilingual_as_first_class_output(tmp_path: Path):
    store = _make_job(tmp_path)
    outputs = export_job(store.job_dir, preset="editing", runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))
    assert "bilingual_srt" in outputs
    assert "compact_srt" in outputs
    text = Path(outputs["bilingual_srt"]).read_text(encoding="utf-8")
    assert "[p1] one bench" in text
    assert "[中文] 长椅一个" in text


def test_export_single_bilingual_format_uses_default_stack_policy(tmp_path: Path):
    store = _make_job(tmp_path)
    write_jsonl(store.translations_path, [
        TranslationSegment("seg1", "s1", "p1", 2, 1.0, 3.0, "one bench", "沙发一个", round_number=1),
        TranslationSegment("seg2", "s2", "p2", 2, 2.0, 4.0, "flash out", "给闪出去", round_number=1),
    ])
    outputs = export_job(store.job_dir, fmt="bilingual", runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))
    text = Path(outputs["bilingual_srt"]).read_text(encoding="utf-8")
    assert "1\n00:00:01,000 --> 00:00:02,000" in text
    assert "2\n00:00:02,000 --> 00:00:03,000" in text
    assert "[p1] one bench" in text
    assert "[p2] flash out" in text
