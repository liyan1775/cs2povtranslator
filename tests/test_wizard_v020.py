from pathlib import Path

from cs2pov.cli import wizard
from cs2pov.domain.models import Player


def test_recommended_player_index_prefers_most_voice_seconds():
    players = [
        Player(steamid="1", name="a", team_number=2, compact_wav_seconds=1.0, voice_packets=100),
        Player(steamid="2", name="b", team_number=2, compact_wav_seconds=10.0, voice_packets=10),
        Player(steamid="3", name="c", team_number=3, compact_wav_seconds=3.0, voice_packets=1000),
    ]
    assert wizard.recommended_player_index(players) == 2


def test_config_from_defaults_uses_product_defaults(tmp_path):
    cfg = wizard.config_from_defaults({}, tmp_path)
    assert cfg.output_root == str(tmp_path)
    assert cfg.whisper_model == "base"
    assert cfg.transcription_mode == "round"
    assert cfg.whisper_vad_filter is True
    assert cfg.filter_hallucinations is True
    assert cfg.max_subtitle_segment_seconds == 10.0
