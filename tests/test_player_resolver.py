"""Tests for player_resolver module (v0.1 — demoparser2-based)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cs2tl.player_resolver import PlayerInfo, resolve_players


class TestPlayerInfo:
    def test_creates_info(self):
        info = PlayerInfo(steam_id="76561198000000001", player_name="donk", team="2")
        assert info.player_name == "donk"
        assert info.team == "2"

    def test_defaults_to_unknown(self):
        info = PlayerInfo(steam_id="76561198000000001")
        assert info.team == "unknown"
        assert info.player_name == "76561198000000001"


class TestResolvePlayers:
    def test_falls_back_to_steam_id_when_demoparser2_unavailable(self):
        """Without demoparser2, all players show as steam_id + unknown team."""
        steam_ids = ["76561198000000001", "76561198000000002"]
        with patch("demoparser2.DemoParser", side_effect=ImportError):
            result = resolve_players(Path("/fake/demo.dem"), steam_ids)
            assert "76561198000000001" in result
            assert result["76561198000000001"].player_name == "76561198000000001"
            assert result["76561198000000001"].team == "unknown"

    def test_resolves_name_and_team_from_demoparser2(self):
        """Names and teams come from demoparser2.parse_player_info() (D6 decision)."""
        import pandas as pd

        steam_ids = ["76561198362970723", "76561198147750283"]

        mock_df = pd.DataFrame([
            {"steamid": 76561198362970723, "name": "xTRAVIS", "team_number": 2},
            {"steamid": 76561198147750283, "name": "baz", "team_number": 3},
            # BOT — should be filtered out
            {"steamid": 12, "name": "BOT Steve", "team_number": 2},
        ])

        mock_parser = MagicMock()
        mock_parser.parse_player_info.return_value = mock_df

        with patch("demoparser2.DemoParser", return_value=mock_parser):
            result = resolve_players(Path("/fake/demo.dem"), steam_ids)

        assert result["76561198362970723"].player_name == "xTRAVIS"
        assert result["76561198362970723"].team == "2"
        assert result["76561198147750283"].player_name == "baz"
        assert result["76561198147750283"].team == "3"
        # BOT should not appear in result
        assert "12" not in result

    def test_demoparser2_crash_falls_back_gracefully(self):
        """If demoparser2 throws, players get steam_id as name + unknown team."""
        steam_ids = ["76561198000000001"]

        with patch("demoparser2.DemoParser", side_effect=RuntimeError("boom")):
            result = resolve_players(Path("/fake/demo.dem"), steam_ids)

        assert result["76561198000000001"].player_name == "76561198000000001"
        assert result["76561198000000001"].team == "unknown"

    def test_handles_zst_path(self):
        """ZST paths trigger decompression via shared.decompress_zst."""
        import pandas as pd

        mock_df = pd.DataFrame([
            {"steamid": 76561198000000001, "name": "donk", "team_number": 2},
        ])

        mock_parser = MagicMock()
        mock_parser.parse_player_info.return_value = mock_df

        with patch("demoparser2.DemoParser", return_value=mock_parser), \
             patch("cs2tl.player_resolver.decompress_zst") as mock_decompress:
            mock_decompress.return_value = Path("/tmp/test.dem")
            result = resolve_players(Path("/fake/demo.dem.zst"), ["76561198000000001"])

            mock_decompress.assert_called_once()
            assert result["76561198000000001"].player_name == "donk"
