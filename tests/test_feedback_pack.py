import json
import zipfile
from pathlib import Path

from cs2pov.cli.commands import run_feedback
from cs2pov.application.workspace_runtime import WorkspaceRuntime


def test_feedback_pack_excludes_large_audio_dirs(tmp_path, monkeypatch):
    job = tmp_path / "output" / "20260610_de_mirage"
    (job / "artifacts" / "voice").mkdir(parents=True)
    (job / "artifacts" / "temp_audio").mkdir(parents=True)
    (job / "final").mkdir()
    (job / "artifacts").mkdir(exist_ok=True)
    (job / "manifest.json").write_text(json.dumps({"config": {"llm_api_key": "[已配置-已隐藏]"}}, ensure_ascii=False), encoding="utf-8")
    (job / "progress.log").write_text("ok", encoding="utf-8")
    (job / "artifacts" / "transcription_coverage.json").write_text("{}", encoding="utf-8")
    (job / "artifacts" / "voice" / "huge.wav").write_bytes(b"audio")
    (job / "artifacts" / "temp_audio" / "slice.wav").write_bytes(b"audio")
    (job / "final" / "team_2.bilingual.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi", encoding="utf-8")

    out = tmp_path / "feedback.zip"
    assert run_feedback(job, out=out, runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1)) == 0
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "progress.log" in names
    assert "final/team_2.bilingual.srt" in names
    assert "artifacts/voice/huge.wav" not in names
    assert "artifacts/temp_audio/slice.wav" not in names



def test_feedback_pack_sanitizes_local_absolute_paths(tmp_path):
    job = tmp_path / "output" / "20260610_de_mirage"
    (job / "artifacts").mkdir(parents=True)
    (job / "final").mkdir()
    manifest = {
        "job_id": "20260610_de_mirage",
        "config": {"llm_api_key": "[已配置-已隐藏]"},
        "artifacts": {
            "bilingual_srt": r"D:\个人项目\cs2pov\output\20260610_de_mirage\final\team_2.bilingual.srt",
            "demo_path": r"D:\agent_workspace\cs2demos\match.dem",
        },
    }
    demo_info = {"input_path": r"D:\agent_workspace\cs2demos\match.dem.zst", "map_name": "de_mirage"}
    (job / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (job / "artifacts" / "demo_info.json").write_text(json.dumps(demo_info, ensure_ascii=False), encoding="utf-8")
    (job / "progress.log").write_text("ok", encoding="utf-8")
    (job / "final" / "team_2.bilingual.srt").write_text("srt", encoding="utf-8")

    out = tmp_path / "feedback.zip"
    assert run_feedback(job, out=out, runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1)) == 0
    with zipfile.ZipFile(out) as zf:
        manifest_text = zf.read("manifest.json").decode("utf-8")
        demo_text = zf.read("artifacts/demo_info.json").decode("utf-8")
        readme = zf.read("README_FEEDBACK.txt").decode("utf-8")

    assert "D:" not in manifest_text
    assert "D:" not in demo_text
    assert "D:" not in readme
    assert "个人项目" not in manifest_text
    assert "final/team_2.bilingual.srt" in manifest_text
    assert "[已隐藏-本地路径]/match.dem.zst" in demo_text


def test_feedback_pack_sanitizes_progress_log_paths(tmp_path):
    job = tmp_path / "output" / "20260610_de_mirage"
    (job / "artifacts").mkdir(parents=True)
    (job / "final").mkdir()
    (job / "manifest.json").write_text(json.dumps({"job_id": "20260610_de_mirage"}, ensure_ascii=False), encoding="utf-8")
    (job / "progress.log").write_text(
        r"[INFO] 输出 bilingual_srt: D:\个人项目\cs2pov\output\20260610_de_mirage\final\team_2.bilingual.srt"
        "\n"
        r"[INFO] source demo: D:\agent_workspace\cs2demos\match.dem.zst"
        "\n",
        encoding="utf-8",
    )
    (job / "artifacts" / "demo_info.json").write_text("{}", encoding="utf-8")
    (job / "final" / "team_2.bilingual.srt").write_text("srt", encoding="utf-8")

    out = tmp_path / "feedback.zip"
    assert run_feedback(job, out=out, runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1)) == 0
    with zipfile.ZipFile(out) as zf:
        progress = zf.read("progress.log").decode("utf-8")

    assert "D:" not in progress
    assert "个人项目" not in progress
    assert "agent_workspace" not in progress
    assert "final/team_2.bilingual.srt" in progress
    assert "[已隐藏-本地路径]/match.dem.zst" in progress
