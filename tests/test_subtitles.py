"""Tests for subtitles module."""

from __future__ import annotations

from unittest.mock import MagicMock

from cs2tl.subtitles import (
    format_srt_entry,
    format_srt_timestamp,
    write_srt,
)


class TestTimestampFormatting:
    def test_zero(self):
        assert format_srt_timestamp(0) == "00:00:00,000"

    def test_one_second(self):
        assert format_srt_timestamp(1.0) == "00:00:01,000"

    def test_one_minute(self):
        assert format_srt_timestamp(62.5) == "00:01:02,500"

    def test_one_hour(self):
        # float precision: 3723.999 has millis ≈ 999 or 998
        ts = format_srt_timestamp(3723.999)
        assert ts == "01:02:03,999" or ts == "01:02:03,998"
        assert format_srt_timestamp(3724.0) == "01:02:04,000"


class TestFormatEntry:
    def test_player_prefix_format(self):
        """Every SRT entry MUST have bilingual [EN]/[中] format."""
        entry = format_srt_entry(1, 1.5, 3.2, "donk", "let's go A", "我来架A小")
        assert "1" in entry.split("\n")[0]
        assert "[EN] donk: let's go A" in entry
        assert "[中] 我来架A小" in entry
        assert "00:00:01,500 --> 00:00:03,200" in entry

    def test_unicode_handling(self):
        entry = format_srt_entry(1, 0.0, 1.0, "ZywOo", "hold B site!", "守B包点！")
        assert "ZywOo" in entry
        assert "hold B site!" in entry
        assert "守B包点" in entry

    def test_same_text_no_duplicate(self):
        """When original == translated, don't duplicate the line."""
        entry = format_srt_entry(1, 0.0, 1.0, "donk", "AWP", "AWP")
        # Should only appear once
        assert entry.count("AWP") == 1


class TestWriteSRT:
    def _make_seg(self, player_name: str, team: str, translated_text: str, start: float = 1.0):
        seg = MagicMock()
        seg.steam_id = "sid1"
        seg.player_name = player_name
        seg.team = team
        seg.start_time = start
        seg.end_time = start + 2.0
        seg.translated_text = translated_text
        seg.original_text = "original"
        seg.round_number = 1
        seg.warnings = []
        return seg

    def test_writes_per_team_files(self, tmp_path):
        segs = [
            self._make_seg("donk", "T", "我来架A小", 10.0),
            self._make_seg("s1mple", "CT", "守B点", 20.0),
        ]
        result = write_srt(segs, tmp_path, "test_demo")
        assert "T" in result
        assert "CT" in result
        assert result["T"].exists()
        assert result["CT"].exists()

    def test_empty_team_produces_placeholder(self, tmp_path):
        """Empty team gets a single placeholder SRT entry."""
        result = write_srt([], tmp_path, "test_demo")
        # Empty segments → no teams → empty result dict
        assert len(result) == 0

        # But if there IS a team with no segments... the _build_srt_content
        # handles it at the per-team level
        from cs2tl.subtitles import _build_srt_content
        content = _build_srt_content([])
        assert "无语音通讯" in content

    def test_player_name_in_output(self, tmp_path):
        segs = [self._make_seg("donk", "T", "我在中路", 5.0)]
        result = write_srt(segs, tmp_path, "demo")
        content = result["T"].read_text(encoding="utf-8")
        # Bilingual: [EN] on first line, [中] on translation line
        assert "[EN] donk: original" in content
        assert "[中] 我在中路" in content

    def test_utf8_bom_encoding(self, tmp_path):
        segs = [self._make_seg("donk", "T", "测试编码", 1.0)]
        result = write_srt(segs, tmp_path, "demo", encoding="utf-8-bom")
        raw = result["T"].read_bytes()
        # UTF-8 BOM: EF BB BF
        assert raw[:3] == b"\xef\xbb\xbf"
