"""Tests for player_resolver module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from cs2tl.player_resolver import PlayerInfo, resolve_players, _looks_like_temp_suffix


class TestPlayerInfo:
    def test_creates_info(self):
        info = PlayerInfo(steam_id="76561198000000001", player_name="donk", team="T")
        assert info.player_name == "donk"
        assert info.team == "T"


class TestLooksLikeTempSuffix:
    def test_short_alphanumeric_is_temp(self):
        # Exactly 8 chars, all lowercase+digits = temp suffix from Go mktemp
        assert _looks_like_temp_suffix("s6m0aepr") is True
        assert _looks_like_temp_suffix("ukxddvy2") is True

    def test_player_name_is_not_temp(self):
        assert _looks_like_temp_suffix("xTRAVIS") is False
        assert _looks_like_temp_suffix("donk") is False
        # Short gamertags with digits should NOT be flagged as temp
        assert _looks_like_temp_suffix("l23n") is False
        assert _looks_like_temp_suffix("m0T11-") is False


class TestResolvePlayers:
    def test_falls_back_to_steam_id_when_no_filename_info(self):
        """Without player names in filenames, falls back to steam_id."""
        wav_files = {
            "76561198000000001": Path("/tmp/voices/some_file_76561198000000001.wav"),
            "76561198000000002": Path("/tmp/voices/some_file_76561198000000002.wav"),
        }
        result = resolve_players(Path("/fake/demo.dem"), wav_files)
        assert "76561198000000001" in result
        # Filename doesn't have player_name format, so falls back to steam_id
        assert result["76561198000000001"].team == "unknown"

    def test_extracts_player_name_from_wav_filename(self):
        """csgove filename format: {prefix}_{PLAYER_NAME}_{STEAM_ID}.wav"""
        wav_files = {
            "76561198362970723": Path("/tmp/voices/demo_temp_xTRAVIS_76561198362970723.wav"),
            "76561198147750283": Path("/tmp/voices/demo_temp_baz_76561198147750283.wav"),
        }
        result = resolve_players(Path("/fake/demo.dem"), wav_files)
        assert result["76561198362970723"].player_name == "xTRAVIS"
        assert result["76561198147750283"].player_name == "baz"
