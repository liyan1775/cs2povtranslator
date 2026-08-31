from pathlib import Path

from cs2pov.cli.commands import _parse_rounds_arg, main
from cs2pov.domain.models import PipelineConfig, Round, TranslationSegment
from cs2pov.pipeline.manifest import PipelineManifest
from cs2pov.services.comms_service import CommsRenderOptions, CommsService, parse_clock, format_clock, format_comms_clock, parse_comms_clock_to_elapsed, format_elapsed
from cs2pov.services.player_alias_service import save_player_aliases
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_json, write_json, write_jsonl
from cs2pov.application.workspace_runtime import WorkspaceRuntime


def _fake_job(tmp_path: Path) -> ArtifactStore:
    store = ArtifactStore(tmp_path / "job")
    store.ensure_dirs()
    cfg = PipelineConfig(selected_team_number=2, export_scope="pov_team")
    PipelineManifest.create("job", cfg).save(store.manifest_path)
    write_json(store.rounds_path, [
        Round(round_number=1, start_time=100.0, end_time=220.0),
        Round(round_number=2, start_time=300.0, end_time=420.0),
    ])
    write_jsonl(store.translations_path, [
        TranslationSegment(
            id="r1a", steamid="765", player_name="Ebule", team_number=2,
            start_time=123.0, end_time=125.0, original_text="one con, maybe two", translated_text="连接一个，可能两个", round_number=1,
        ),
        TranslationSegment(
            id="r1b", steamid="888", player_name="chopper", team_number=2,
            start_time=127.0, end_time=128.0, original_text="wait wait", translated_text="等等", round_number=1,
        ),
        TranslationSegment(
            id="r2a", steamid="999", player_name="enemy", team_number=3,
            start_time=320.0, end_time=321.0, original_text="not our team", translated_text="不是本队", round_number=2,
        ),
    ])
    save_player_aliases(store, {"765": "donk"})
    return store


def test_clock_helpers():
    assert parse_clock("1:55") == 115
    assert parse_clock("0:07") == 7
    assert format_clock(92) == "1:32"


def test_build_review_outputs_editable_round_yaml_and_feed(tmp_path: Path):
    store = _fake_job(tmp_path)

    outputs = CommsService().build_review(store, selected_team_number=2, selected_pov_steamid=None, export_scope="pov_team", runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))

    feed = read_json(Path(outputs["comms_feed_json"]))
    assert feed["schema_version"] == 1
    assert feed["rounds"][0]["round"] == 1
    assert feed["rounds"][0]["messages"][0]["speaker"] == "donk"
    assert feed["rounds"][0]["freeze_seconds"] == 0.0
    assert feed["rounds"][0]["time_display"] == "none"
    assert feed["rounds"][0]["duration_seconds"] == 120.0
    assert feed["rounds"][0]["messages"][0]["show_at_seconds"] == 23.0
    assert (store.review_dir / "comms_rounds" / "round_01.yaml").exists()
    assert "zh:" in (store.review_dir / "comms_rounds" / "round_01.yaml").read_text(encoding="utf-8")
    assert not (store.review_dir / "comms_rounds" / "round_02.yaml").exists()


def test_render_png_from_review_yaml(tmp_path: Path):
    store = _fake_job(tmp_path)
    CommsService().build_review(store, selected_team_number=2, selected_pov_steamid=None, export_scope="pov_team", runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))

    outputs = CommsService().render(
        store,
        rounds={1},
        formats=["png"],
        options=CommsRenderOptions(width=640, height=360, panel_width=260, panel_height=220, right_margin=16, max_messages=2),
        runtime=WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1),
    )

    path = Path(outputs["round_01_png"])
    assert path.exists()
    assert path.suffix == ".png"


def test_comms_cli_build_review_json(tmp_path: Path, capsys, monkeypatch):
    store = _fake_job(tmp_path)
    monkeypatch.setattr("cs2pov.cli.commands._resolve_write_runtime", lambda: WorkspaceRuntime(tmp_path / "workspace", "ws", 1, 1))

    code = main(["comms", "build-review", str(store.job_dir), "--rounds", "1", "--json"])

    assert code == 0
    captured = capsys.readouterr()
    payload = __import__("json").loads(captured.out)
    assert "comms_feed_json" in payload
    assert captured.err.count("警告：正在原位置修改外部旧 Job") == 1
    assert (store.review_dir / "comms_rounds" / "round_01.yaml").exists()


def test_parse_rounds_arg():
    assert _parse_rounds_arg("1,3-5") == {1, 3, 4, 5}
    assert _parse_rounds_arg(None) is None



def test_comms_clock_accounts_for_freeze_time():
    # Round-clock display is retained as an experimental/manual option, but it
    # is not the v0.9.8 default because preparation time varies across sources.
    assert format_comms_clock(1.7, 5.0, 115) == "准备 0:03"
    assert format_comms_clock(5.0, 5.0, 115) == "1:55"
    assert format_comms_clock(7.9, 5.0, 115) == "1:52"
    assert parse_comms_clock_to_elapsed("准备 0:03", 5.0, 115) == 2.0
    assert parse_comms_clock_to_elapsed("1:52", 5.0, 115) == 8.0

def test_v091_overlay_defaults_are_floating_cards():
    options = CommsRenderOptions()
    assert options.panel_width == 460
    assert options.right_margin == 16
    assert options.max_messages == 6
    assert options.font_size_zh == 24
    assert options.show_outer_panel is False
    assert options.fade_seconds > 0
    assert options.time_display == "none"


def test_elapsed_time_display_helper_is_optional():
    assert format_elapsed(7.4) == "+0:07"
    assert format_elapsed(67.8) == "+1:08"
