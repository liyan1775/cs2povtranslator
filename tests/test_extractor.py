"""Tests for extractor module (v0.1 — demoparser2 + pyogg)."""

from __future__ import annotations

import ctypes
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cs2tl.errors import CS2tlError
from cs2tl.extractor import (
    ExtractionResult,
    run_extraction,
    SAMPLE_RATE,
    CHANNELS,
    TICK_RATE,
)


class TestRunExtraction:
    def test_extracts_voice_successfully(self, tmp_path):
        """Normal flow: parse_voice → opus_decode → WAV files created."""
        voices_dir = tmp_path / "voices"
        demo = tmp_path / "test.dem"
        demo.write_text("fake")

        # Mock voice packets: 2 players, 2 packets each
        voice_data = [
            {"tick": 6400, "steamid": 76561198000000001, "bytes": b"\x01\x02"},
            {"tick": 12800, "steamid": 76561198000000001, "bytes": b"\x03\x04"},
            {"tick": 6400, "steamid": 76561198000000002, "bytes": b"\x05\x06"},
        ]

        mock_parser = MagicMock()
        mock_parser.parse_voice.return_value = voice_data

        # Mock opus_decode: return 120 samples (5ms @ 24kHz)
        def fake_decode(decoder, data_ptr, data_len, pcm_ptr, max_samples, fec):
            # Fill PCM buffer with some non-zero values
            for j in range(120):
                pcm_ptr[j] = 100
            return 120
        # Actually for ctypes mocking, we need to handle the ctypes.cast properly
        # Simpler: mock the opus module functions

        with patch("demoparser2.DemoParser", return_value=mock_parser), \
             patch("pyogg.opus.opus_decoder_create") as mock_create, \
             patch("pyogg.opus.opus_decode") as mock_decode, \
             patch("wave.open") as mock_wave:

            # Mock decoder creation
            mock_decoder = ctypes.c_void_p(1)
            mock_create.return_value = mock_decoder

            # Mock decode: return 240 samples per frame
            mock_decode.side_effect = lambda dec, data, dlen, pcm, max_s, fec: 240

            # Mock wave writer
            mock_wf = MagicMock()
            mock_wave.open.return_value.__enter__.return_value = mock_wf

            result = run_extraction(demo, voices_dir)

            assert isinstance(result, ExtractionResult)
            assert len(result.wav_files) == 2
            assert "76561198000000001" in result.wav_files
            assert "76561198000000002" in result.wav_files
            # Verify timestamps
            assert len(result.voice_timestamps["76561198000000001"]) == 2
            # First packet at tick 6400 → 100.0s
            assert result.voice_timestamps["76561198000000001"][0][0] == pytest.approx(100.0, abs=0.1)
            assert result.skipped_frames == 0

    def test_zero_voice_raises_e1_0003(self, tmp_path):
        """Empty voice data → E1-0003 (not an error in CLI — exit 0)."""
        voices_dir = tmp_path / "voices"
        demo = tmp_path / "test.dem"
        demo.write_text("fake")

        mock_parser = MagicMock()
        mock_parser.parse_voice.return_value = []

        with patch("demoparser2.DemoParser", return_value=mock_parser):
            with pytest.raises(CS2tlError) as exc_info:
                run_extraction(demo, voices_dir)
            assert exc_info.value.code == "E1-0003"

    def test_opus_decoder_null_raises_e1_0004(self, tmp_path):
        """opus_decoder_create returns NULL → E1-0004."""
        voices_dir = tmp_path / "voices"
        demo = tmp_path / "test.dem"
        demo.write_text("fake")

        voice_data = [
            {"tick": 6400, "steamid": 76561198000000001, "bytes": b"\x01\x02"},
        ]

        mock_parser = MagicMock()
        mock_parser.parse_voice.return_value = voice_data

        with patch("demoparser2.DemoParser", return_value=mock_parser), \
             patch("pyogg.opus.opus_decoder_create", return_value=None):

            with pytest.raises(CS2tlError) as exc_info:
                run_extraction(demo, voices_dir)
            assert exc_info.value.code == "E1-0004"

    def test_skips_corrupt_opus_frames(self, tmp_path):
        """opus_decode < 0 → skip frame + increment counter (D5 decision)."""
        voices_dir = tmp_path / "voices"
        demo = tmp_path / "test.dem"
        demo.write_text("fake")

        voice_data = [
            {"tick": 6400, "steamid": 76561198000000001, "bytes": b"\x01\x02"},   # good
            {"tick": 6416, "steamid": 76561198000000001, "bytes": b"\x03\x04"},   # corrupt
            {"tick": 6432, "steamid": 76561198000000001, "bytes": b"\x05\x06"},   # good
        ]

        mock_parser = MagicMock()
        mock_parser.parse_voice.return_value = voice_data

        call_count = [0]

        def side_effect(decoder, data_ptr, data_len, pcm_ptr, max_samples, fec):
            call_count[0] += 1
            if call_count[0] == 2:
                return -4  # corrupt frame
            # Fill some PCM
            for j in range(120):
                pcm_ptr[j] = 100
            return 120

        with patch("demoparser2.DemoParser", return_value=mock_parser), \
             patch("pyogg.opus.opus_decoder_create", return_value=ctypes.c_void_p(1)), \
             patch("pyogg.opus.opus_decode") as mock_decode, \
             patch("wave.open"):

            mock_decode.side_effect = side_effect

            result = run_extraction(demo, voices_dir)

            assert result.skipped_frames == 1
            assert len(result.wav_files) == 1  # still writes WAV for this player
            # Only good frames contribute to timestamps
            assert len(result.voice_timestamps["76561198000000001"]) == 2  # 2 good frames

    def test_zst_decompresses_via_shared(self, tmp_path):
        """.dem.zst input → calls shared.decompress_zst."""
        voices_dir = tmp_path / "voices"
        demo_zst = tmp_path / "test.dem.zst"
        demo_zst.write_text("fake compressed")

        voice_data = [
            {"tick": 6400, "steamid": 76561198000000001, "bytes": b"\x01\x02"},
        ]

        mock_parser = MagicMock()
        mock_parser.parse_voice.return_value = voice_data

        with patch("demoparser2.DemoParser", return_value=mock_parser), \
             patch("pyogg.opus.opus_decoder_create", return_value=ctypes.c_void_p(1)), \
             patch("pyogg.opus.opus_decode", return_value=240), \
             patch("wave.open"), \
             patch("cs2tl.extractor.decompress_zst") as mock_decompress:

            mock_decompress.return_value = tmp_path / "test_decompressed.dem"

            result = run_extraction(demo_zst, voices_dir)

            mock_decompress.assert_called_once()
            assert len(result.wav_files) == 1

    def test_filters_bot_players(self, tmp_path):
        """Players with non-standard Steam IDs (BOTs) are excluded."""
        voices_dir = tmp_path / "voices"
        demo = tmp_path / "test.dem"
        demo.write_text("fake")

        voice_data = [
            {"tick": 6400, "steamid": 12, "bytes": b"\x01\x02"},                       # BOT
            {"tick": 6400, "steamid": 76561198000000001, "bytes": b"\x03\x04"},         # real
        ]

        mock_parser = MagicMock()
        mock_parser.parse_voice.return_value = voice_data

        with patch("demoparser2.DemoParser", return_value=mock_parser), \
             patch("pyogg.opus.opus_decoder_create", return_value=ctypes.c_void_p(1)), \
             patch("pyogg.opus.opus_decode", return_value=240), \
             patch("wave.open"):

            result = run_extraction(demo, voices_dir)

            # BOT must not appear
            assert "12" not in result.wav_files
            assert "76561198000000001" in result.wav_files
