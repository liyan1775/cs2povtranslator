"""Auto-download csgove (csgo-voice-extractor) binary from GitHub Releases.

Detects OS + architecture, fetches the latest release download URL, and
places the binary in the local data directory.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import tempfile
from pathlib import Path
from urllib.request import urlopen

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com/repos/akiver/csgo-voice-extractor/releases/latest"
_GITHUB_RELEASES = "https://github.com/akiver/csgo-voice-extractor/releases/latest"
_BINARY_NAME = "csgove"


def _detect_platform_tag() -> str:
    """Map sys.platform + platform.machine() to a GitHub release asset tag."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        return "windows-amd64" if machine in ("amd64", "x86_64") else "windows-arm64"
    elif system == "darwin":
        return "darwin-amd64" if machine in ("amd64", "x86_64") else "darwin-arm64"
    elif system == "linux":
        return "linux-amd64" if machine in ("amd64", "x86_64") else "linux-arm64"
    else:
        raise RuntimeError(f"Unsupported platform: {system}/{machine}")


def download_csgove(target_dir: Path | None = None) -> Path:
    """Download the latest csgove binary to ``target_dir/bin/``.

    Args:
        target_dir: Parent directory (defaults to ``cs2tl-data/`` from config).

    Returns:
        Absolute path to the downloaded binary.

    Raises:
        RuntimeError: If download fails or platform is unsupported.
    """
    import json as _json

    if target_dir is None:
        from cs2tl.config import default_data_dir
        target_dir = default_data_dir()

    bin_dir = target_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    tag = _detect_platform_tag()
    suffix = ".exe" if platform.system().lower() == "windows" else ""
    binary_path = bin_dir / f"{_BINARY_NAME}{suffix}"

    # Already downloaded?
    if binary_path.exists():
        logger.info("csgove already exists at %s", binary_path)
        return binary_path

    # Resolve download URL from GitHub API
    logger.info("Fetching latest csgove release info from GitHub...")
    try:
        with urlopen(_GITHUB_API, timeout=30) as resp:
            release_data = _json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(
            f"Failed to fetch release info from GitHub: {e}. "
            f"Download csgove manually from {_GITHUB_RELEASES}"
        ) from e

    # Find the matching asset
    assets = release_data.get("assets", [])
    download_url = None
    for asset in assets:
        name = asset.get("name", "")
        if tag in name.lower():
            download_url = asset.get("browser_download_url")
            break

    if download_url is None:
        raise RuntimeError(
            f"No csgove release found for platform '{tag}'. "
            f"Available assets: {', '.join(a.get('name', '?') for a in assets)}. "
            f"Download manually from {_GITHUB_RELEASES}"
        )

    # Download
    print(f"正在下载 csgove ({tag})...")
    logger.info("Downloading csgove from %s", download_url)
    try:
        with urlopen(download_url, timeout=300) as resp:
            # Stream to temp file then move
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="csgove_")
            try:
                with os.fdopen(tmp_fd, "wb") as f:
                    shutil.copyfileobj(resp, f)
                # Move to final location
                shutil.move(tmp_path, binary_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
    except Exception as e:
        raise RuntimeError(
            f"Download failed: {e}. "
            f"Download csgove manually from {_GITHUB_RELEASES} "
            f"and place it in {bin_dir}"
        ) from e

    # Make executable on Unix
    if platform.system().lower() != "windows":
        binary_path.chmod(binary_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"✅ csgove 已下载到: {binary_path}")
    logger.info("csgove downloaded successfully to %s", binary_path)
    return binary_path
