"""Tests for voice_aligner module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from cs2tl.voice_aligner import align_segments


class TestAlignSegments:
    def test_no_op_when_demoparser2_unavailable(self):
        """Segments pass through unchanged when demoparser2 fails."""

        class FakeSeg:
            steam_id = "76561198000000001"
            start_time = 1.0
            end_time = 2.0

        seg = FakeSeg()
        result = align_segments([seg], Path("/nonexistent/demo.dem"))
        assert len(result) == 1
        assert result[0].start_time == 1.0  # unchanged
        assert result[0].end_time == 2.0    # unchanged

    @patch("demoparser2.DemoParser")
    def test_aligns_timestamps_from_ticks(self, mock_parser_cls):
        """Timestamps are replaced with voice-packet tick times."""
        mock_parser = MagicMock()
        # Voice packets at ticks 6400, 6416, 12800 (100s, 100.25s, 200s)
        # First two are within 0.5s → merge into one utterance (100, 100.25)
        # Third is separate → utterance (200, 200)
        mock_parser.parse_voice.return_value = [
            {"tick": 6400, "steamid": 76561198000000001, "bytes": b"x"},
            {"tick": 6416, "steamid": 76561198000000001, "bytes": b"y"},
            {"tick": 12800, "steamid": 76561198000000001, "bytes": b"z"},
        ]
        mock_parser_cls.return_value = mock_parser

        class FakeSeg:
            steam_id = "76561198000000001"
            start_time = 1.0
            end_time = 2.5

        segs = [FakeSeg(), FakeSeg(), FakeSeg()]
        result = align_segments(segs, Path("/fake/demo.dem"))

        # 2 utterances after merge: (100, 100.25) and (200, 200)
        assert result[0].start_time == 100.0   # 6400/64
        assert result[1].start_time == 200.0   # 12800/64
        assert result[2].start_time == 200.0   # fallback to last

    def test_handles_zst_path(self):
        """Non-existent .zst paths are handled gracefully."""
        class FakeSeg:
            steam_id = "76561198000000001"
            start_time = 1.0
            end_time = 2.0

        seg = FakeSeg()
        result = align_segments([seg], Path("/fake/demo.dem.zst"))
        assert len(result) == 1  # no crash
