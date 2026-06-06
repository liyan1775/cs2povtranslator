"""Voice extraction from CS2 demos via csgo-voice-extractor.

Calls the external Go binary `csgove` (csgo-voice-extractor) via subprocess
to extract per-player voice audio from Faceit/community server demos.

Key P1 constraints:
  - Zero-voice early exit (E1-0003, exit code 0)
  - Binary discovery via shutil.which() + doctor command
  - Clear error messages with download URLs
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass

from cs2tl.errors import (
    extractor_failed,
    extractor_not_found,
    no_voice_data,
)

logger = logging.getLogger(__name__)

DEFAULT_CSGOVE_BINARY = "csgove"


@dataclass
class ExtractionResult:
    """Result of voice extraction from a demo file."""

    wav_files: dict[str, Path]  # steam_id -> path to {steam_id}.wav
    output_dir: Path
    duration_seconds: float = 0.0


def check_binary(binary_name: str = DEFAULT_CSGOVE_BINARY) -> Path | None:
    """Check if the csgo-voice-extractor binary is available on PATH.

    Returns the resolved path if found, None otherwise.
    Also checks known install locations (Windows/Linux/macOS).
    """
    resolved = shutil.which(binary_name)
    if resolved is not None:
        return Path(resolved)

    # Check known install locations
    known_paths = []
    if os.name == "nt":
        home = Path.home()
        known_paths = [
            home / "Tools" / "csgo-voice-extractor" / "win32-x64" / f"{binary_name}.exe",
            home / "Tools" / f"{binary_name}.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "csgo-voice-extractor" / "win32-x64" / f"{binary_name}.exe",
        ]
    else:
        known_paths = [
            Path.home() / ".local" / "bin" / binary_name,
            Path("/usr/local/bin") / binary_name,
        ]

    for p in known_paths:
        if p.exists():
            return p

    return None


def run_extraction(
    demo_path: Path,
    output_dir: Path,
    binary: str = DEFAULT_CSGOVE_BINARY,
    mode: str = "split-compact",
    timeout_seconds: int = 300,
) -> ExtractionResult:
    """Run csgo-voice-extractor on a demo file.

    Args:
        demo_path: Path to the .dem file.
        output_dir: Directory for extracted WAV files.
        binary: Name or path of the csgove binary.
        mode: Extraction mode. Default is "split-compact" (per-player WAVs).
        timeout_seconds: Maximum time to wait for extraction.

    Returns:
        ExtractionResult with the mapping of steam_id -> WAV path.

    Raises:
        CS2tlError: E1-0001 if binary not found, E1-0002 if extraction fails,
                    E1-0003 if zero voice data.
    """
    # --- Handle .dem.zst: auto-decompress before processing ---
    tmp_dem: Path | None = None
    if demo_path.suffix == ".zst":
        tmp_dem = _decompress_zst(demo_path)
        logger.info("Decompressed %s -> %s", demo_path.name, tmp_dem.name)
        demo_path = tmp_dem

    # --- P1-1: Binary discovery ---
    binary_path = check_binary(binary)
    if binary_path is None:
        raise extractor_not_found(binary)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Build the command — flags first, then demo path last
    cmd = [
        str(binary_path),
        "-mode", mode,
        "-output", str(output_dir),
        str(demo_path),
    ]

    # Run from csgove's directory so it finds its DLLs (opus.dll, vaudio_celt.dll, etc.)
    working_dir = binary_path.parent

    logger.info("Running extractor: %s (cwd=%s)", " ".join(cmd), working_dir)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(working_dir),
        )
    except subprocess.TimeoutExpired:
        raise extractor_failed(
            str(demo_path),
            f"Extraction timed out after {timeout_seconds}s. The demo may be very large or corrupted.",
        )

    if result.returncode != 0:
        raise extractor_failed(str(demo_path), result.stderr.strip() or result.stdout.strip())

    # Collect WAV files
    # csgove names files as: {demo}_{temp}_{PLAYER_NAME}_{STEAM_ID64}.wav
    # Extract the clean 17-digit Steam ID64 as the key.
    wav_files: dict[str, Path] = {}
    for wav_path in sorted(output_dir.glob("*.wav")):
        steam_id = _extract_steam_id_from_filename(wav_path.stem)
        wav_files[steam_id] = wav_path
        logger.debug("WAV: %s → steam_id=%s", wav_path.name, steam_id)

    # --- P1-4: Zero-voice early exit ---
    if len(wav_files) == 0:
        raise no_voice_data(str(demo_path))

    logger.info("Extracted %d voice files (%d players)", len(wav_files), len(wav_files))

    result_obj = ExtractionResult(
        wav_files=wav_files,
        output_dir=output_dir,
        duration_seconds=0.0,  # not computed here — csgove may report it
    )

    # Clean up temporary decompressed .dem
    if tmp_dem is not None:
        try:
            tmp_dem.unlink()
            logger.debug("Cleaned up temp file: %s", tmp_dem)
        except OSError:
            pass

    return result_obj


def _decompress_zst(zst_path: Path) -> Path:
    """Decompress a .dem.zst file to a temporary .dem file.

    Returns the path to the decompressed .dem file (caller is responsible
    for cleanup).
    """
    import tempfile

    import zstandard as zstd

    with open(zst_path, "rb") as f:
        compressed = f.read()

    dctx = zstd.ZstdDecompressor()
    decompressed = dctx.decompress(compressed)

    # Write to a temp file with the same base name
    base_name = zst_path.stem  # remove .zst → still has .dem
    if not base_name.endswith(".dem"):
        base_name = zst_path.with_suffix("").name  # .dem.zst → name only
    fd, tmp_path = tempfile.mkstemp(suffix=".dem", prefix=base_name + "_")
    with os.fdopen(fd, "wb") as f:
        f.write(decompressed)

    return Path(tmp_path)


def _extract_steam_id_from_filename(stem: str) -> str:
    """Extract the 17-digit Steam ID64 from a csgove WAV filename stem.

    csgove split-compact mode names files as:
      {demo_basename}_{temp_suffix}_{PLAYER_NAME}_{STEAM_ID64}

    The Steam ID64 is the last underscore-separated segment if it's 17 digits.
    Falls back to the full stem if parsing fails.
    """
    import re
    # Match a 17-digit number at the end of the stem (possibly after last _)
    # Steam ID64 format: 7656119XXXXXXXXXX (starts with 7656, 17 digits)
    match = re.search(r"_?(\d{17})$", stem)
    if match:
        return match.group(1)
    return stem
