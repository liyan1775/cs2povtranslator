"""Shared utilities — zstd decompression, used by extractor + player_resolver.

v0.1: Extracted from extractor.py and player_resolver.py to eliminate
duplicate zst decompression logic (3 copies in v0.0 → 1 in v0.1).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def decompress_zst(zst_path: Path) -> Path:
    """Decompress a .dem.zst file to a temporary .dem file.

    Args:
        zst_path: Path to the .dem.zst file.

    Returns:
        Path to the decompressed .dem file (caller is responsible for cleanup).

    Raises:
        OSError: If the file cannot be read or written.
    """
    import zstandard as zstd

    logger.debug("Decompressing %s", zst_path.name)
    with open(zst_path, "rb") as f:
        compressed = f.read()

    dctx = zstd.ZstdDecompressor()
    decompressed = dctx.decompress(compressed)

    # Build temp filename that preserves the original demo name for traceability
    base = zst_path.stem  # removes .zst → still has .dem
    if not base.endswith(".dem"):
        base = zst_path.with_suffix("").name  # .dem.zst → basename only

    fd, tmp_path = tempfile.mkstemp(suffix=".dem", prefix=base + "_")
    with os.fdopen(fd, "wb") as f:
        f.write(decompressed)

    return Path(tmp_path)
