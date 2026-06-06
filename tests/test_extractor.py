"""Tests for extractor module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cs2tl.errors import CS2tlError
from cs2tl.extractor import (
    ExtractionResult,
    check_binary,
    run_extraction,
)


class TestCheckBinary:
    def test_returns_none_when_not_found(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: None)
        # Also disable known-path fallback so this test doesn't find real installs
        monkeypatch.setattr("cs2tl.extractor.Path.exists", lambda self: False)
        result = check_binary("csgove")
        assert result is None

    def test_returns_path_when_found(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: "/usr/bin/csgove")
        result = check_binary("csgove")
        assert result == Path("/usr/bin/csgove")


class TestRunExtraction:
    def test_raises_e1_0001_when_binary_not_found(self, tmp_dir):
        with patch("cs2tl.extractor.check_binary", return_value=None):
            with pytest.raises(CS2tlError) as exc_info:
                run_extraction(Path("test.dem"), tmp_dir / "voices")
            assert exc_info.value.code == "E1-0001"

    def test_raises_e1_0002_on_nonzero_exit(self, tmp_dir):
        demo = tmp_dir / "test.dem"
        demo.write_text("fake")
        out = tmp_dir / "voices"
        out.mkdir()

        with patch("cs2tl.extractor.check_binary", return_value=Path("/fake/csgove")):
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = "panic: invalid demo"
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(CS2tlError) as exc_info:
                    run_extraction(demo, out)
                assert exc_info.value.code == "E1-0002"

    def test_raises_e1_0003_on_zero_wavs(self, tmp_dir):
        demo = tmp_dir / "test.dem"
        demo.write_text("fake")
        out = tmp_dir / "voices"
        out.mkdir()

        with patch("cs2tl.extractor.check_binary", return_value=Path("/fake/csgove")):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            with patch("subprocess.run", return_value=mock_result):
                with patch.object(Path, "glob", return_value=[]):
                    with pytest.raises(CS2tlError) as exc_info:
                        run_extraction(demo, out)
                    assert exc_info.value.code == "E1-0003"

    def test_returns_extraction_result_on_success(self, tmp_dir):
        demo = tmp_dir / "test.dem"
        demo.write_text("fake")
        out = tmp_dir / "voices"
        out.mkdir()

        fake_wav = out / "76561198000000001.wav"
        fake_wav.write_bytes(b"RIFF....")

        with patch("cs2tl.extractor.check_binary", return_value=Path("/fake/csgove")):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stderr = ""
            with patch("subprocess.run", return_value=mock_result):
                result = run_extraction(demo, out)
                assert isinstance(result, ExtractionResult)
                assert "76561198000000001" in result.wav_files
