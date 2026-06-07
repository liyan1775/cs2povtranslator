"""Integration test for extractor — uses a real CS2 demo (D8 decision).

Requires a real .dem file. Set CS2TL_TEST_DEMO env var to override the
default path, or skip if none is available.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cs2tl.extractor import (
    SAMPLE_RATE,
    CHANNELS,
    run_extraction,
    ExtractionResult,
)

# Default test demo path — override with CS2TL_TEST_DEMO env var
_DEFAULT_DEMO = Path("D:/agent_workspace/cs2demos/1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst")


def _get_test_demo() -> Path | None:
    """Resolve test demo path from env var or default."""
    env_path = os.environ.get("CS2TL_TEST_DEMO")
    if env_path:
        return Path(env_path)
    if _DEFAULT_DEMO.exists():
        return _DEFAULT_DEMO
    return None


@pytest.mark.integration
@pytest.mark.slow
class TestExtractorIntegration:
    """Real-demo integration tests (D8 decision — 1 real demo test)."""

    def test_extracts_voice_from_real_demo(self, tmp_path):
        """Extract voice from a real CS2 Faceit demo and verify output."""
        demo_path = _get_test_demo()
        if demo_path is None:
            pytest.skip("No real demo available — set CS2TL_TEST_DEMO env var")

        voices_dir = tmp_path / "voices"
        result = run_extraction(demo_path, voices_dir)

        assert isinstance(result, ExtractionResult)

        # Should have at least 1 player with voice
        assert len(result.wav_files) >= 1, "Expected at least 1 player with voice"

        # Each WAV file should exist and be a valid WAV
        for sid, wav_path in result.wav_files.items():
            assert wav_path.exists(), f"WAV missing for player {sid}"
            assert wav_path.stat().st_size > 44, f"WAV too small for player {sid} (empty voice?)"

            # WAV header check: "RIFF" magic
            header = wav_path.read_bytes()[:4]
            assert header == b"RIFF", f"Not a valid WAV file for player {sid}"

        # Voice timestamps should exist for every player
        for sid in result.wav_files:
            assert sid in result.voice_timestamps, f"No timestamps for player {sid}"
            ts_list = result.voice_timestamps[sid]
            assert len(ts_list) >= 1, f"Empty timestamps for player {sid}"

            # Timestamps should be in increasing order
            for i in range(1, len(ts_list)):
                assert ts_list[i][0] >= ts_list[i-1][0], (
                    f"Timestamps not sorted for player {sid}"
                )

            # Check timestamp ranges are sane (0 to ~3600 seconds for a match)
            for start, end in ts_list:
                assert 0 <= start <= 7200, f"Timestamp {start}s out of range"
                assert end > start, f"End time {end}s <= start time {start}s"
                duration = end - start
                # Opus frame = 120ms max, but multiple packets may be contiguous
                assert 0 < duration < 10.0, f"Frame duration {duration}s suspicious"

        # Output directory should exist
        assert voices_dir.exists()

    def test_extracted_wav_has_correct_format(self, tmp_path):
        """Verify WAV files have the correct audio format (24kHz, mono, 16-bit)."""
        import wave

        demo_path = _get_test_demo()
        if demo_path is None:
            pytest.skip("No real demo available — set CS2TL_TEST_DEMO env var")

        voices_dir = tmp_path / "voices"
        result = run_extraction(demo_path, voices_dir)

        for sid, wav_path in result.wav_files.items():
            with wave.open(str(wav_path), "rb") as wf:
                assert wf.getnchannels() == CHANNELS, (
                    f"Expected {CHANNELS} channel(s), got {wf.getnchannels()}"
                )
                assert wf.getframerate() == SAMPLE_RATE, (
                    f"Expected {SAMPLE_RATE} Hz, got {wf.getframerate()}"
                )
                assert wf.getsampwidth() == 2, (
                    f"Expected 16-bit samples, got {wf.getsampwidth() * 8}-bit"
                )
