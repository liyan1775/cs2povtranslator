"""Tests for shared utilities — zstd decompression."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cs2tl.shared import decompress_zst


class TestDecompressZst:
    def test_decompresses_zst_to_temp_dem(self, tmp_path):
        """Normal flow: .dem.zst input → decompressed .dem temp file."""
        zst_path = tmp_path / "test.dem.zst"
        zst_path.write_text("fake compressed data")

        decompressed_content = b"fake demo content"

        with patch("zstandard.ZstdDecompressor") as mock_zstd_cls:
            mock_dctx = mock_zstd_cls.return_value
            mock_dctx.decompress.return_value = decompressed_content

            result = decompress_zst(zst_path)

            # Returns a Path to a temp .dem file
            assert isinstance(result, Path)
            assert result.suffix == ".dem"
            assert result.exists()
            assert result.read_bytes() == decompressed_content

            # Cleanup
            result.unlink()

    def test_preserves_demo_name_in_temp_file(self, tmp_path):
        """The temp file name should include the original demo name for traceability."""
        zst_path = tmp_path / "my-match.dem.zst"
        zst_path.write_text("fake")

        with patch("zstandard.ZstdDecompressor") as mock_zstd_cls:
            mock_dctx = mock_zstd_cls.return_value
            mock_dctx.decompress.return_value = b"content"

            result = decompress_zst(zst_path)

            assert "my-match" in result.name
            assert result.suffix == ".dem"

            result.unlink()

    def test_handles_double_suffix(self, tmp_path):
        """Input with .dem.zst double suffix should strip both correctly."""
        zst_path = tmp_path / "game.dem.zst"
        zst_path.write_text("fake")

        with patch("zstandard.ZstdDecompressor") as mock_zstd_cls:
            mock_dctx = mock_zstd_cls.return_value
            mock_dctx.decompress.return_value = b"content"

            result = decompress_zst(zst_path)

            # Should NOT end with .dem.dem or .dem.zst.dem
            assert result.suffix == ".dem"
            assert ".zst" not in result.name

            result.unlink()
