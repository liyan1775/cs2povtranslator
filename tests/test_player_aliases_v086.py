from pathlib import Path

from cs2pov.adapters.demoparser_adapter import _first_steamid
from cs2pov.cli.player_ops import build_players_report, set_player_alias
from cs2pov.domain.models import TranslationSegment
from cs2pov.services.player_alias_service import apply_player_aliases, save_player_aliases
from cs2pov.services.subtitle_service import SubtitleService
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import read_json, write_json, write_jsonl


def test_player_alias_applies_to_exported_srt(tmp_path: Path):
    store = ArtifactStore(tmp_path / "job")
    store.ensure_dirs()
    write_jsonl(store.translations_path, [TranslationSegment(
        id="seg1", steamid="765", player_name="Ebule", team_number=2,
        start_time=1.0, end_time=2.0, original_text="care cave", translated_text="小心黑屋"
    )])
    save_player_aliases(store, {"765": "donk"})

    outputs = SubtitleService().export_format(store, "bilingual", selected_team_number=2, selected_pov_steamid=None, export_scope="pov_team")
    text = Path(outputs["bilingual_srt"]).read_text(encoding="utf-8")

    assert "[donk] care cave" in text
    assert "[Ebule]" not in text


def test_players_alias_command_resolves_name_and_reports_kda(tmp_path: Path):
    store = ArtifactStore(tmp_path / "job")
    store.ensure_dirs()
    write_json(store.job_dir / "manifest.json", {"job_id": "job", "config": {}})
    write_json(store.voice_manifest_path, {"players": [
        {"steamid": "765", "name": "Ebule", "team_number": 2, "voice_packets": 10, "compact_wav_seconds": 1.5, "kills": 30, "deaths": 11, "assists": 4}
    ]})

    report = set_player_alias(store.job_dir, name="Ebule", display_name="donk")

    assert report["players"][0]["display_name"] == "donk"
    assert report["players"][0]["kda"] == "30-11-4"
    aliases = read_json(store.player_aliases_path)["aliases"]
    assert aliases == {"765": "donk"}


def test_first_steamid_handles_common_player_death_columns():
    row = {"attacker_steamid": 765.0, "user_steamid": "123"}
    assert _first_steamid(row, ["attacker_steamid"]) == "765"
    assert _first_steamid(row, ["user_steamid"]) == "123"
