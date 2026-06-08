"""Doctor — dependency check command."""

from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from cs2tl.errors import CS2tlError


def doctor_cmd(verbose: bool = False) -> int:
    """Check all external dependencies and report status.

    Returns exit code: 0 if all checks pass, 1 if any fail.
    """
    console = Console()
    console.print("\n[bold]cs2tl Doctor — Dependency Check[/bold]\n")

    table = Table(title="Dependency Status")
    table.add_column("Status", style="bold")
    table.add_column("Component")
    table.add_column("Detail")
    table.add_column("Fix", style="dim")

    checks = _run_checks(verbose)
    all_pass = True

    for status, comp, detail, fix in checks:
        style = {"PASS": "green", "FAIL": "red", "WARN": "yellow"}.get(status, "white")
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(status, "?")
        table.add_row(f"[{style}]{icon} {status}[/{style}]", comp, detail, fix)
        if status == "FAIL":
            all_pass = False

    console.print(table)
    console.print()

    if all_pass:
        console.print("[green]All checks passed. Ready to translate![/green]")
    else:
        console.print("[red]Some checks failed. Fix the issues above, then run 'cs2tl doctor' again.[/red]")

    return 0 if all_pass else 1


def _run_checks(verbose: bool) -> list[tuple[str, str, str, str]]:
    return [
        _check_python_version(),
        _check_demoparser2(),
        _check_csgove(interactive=True),
        _check_whisper(),
        _check_awpy(),
        _check_openai(),
        _check_git(),
        *_([_check_config()] if verbose else []),
    ]


def _check_python_version() -> tuple[str, str, str, str]:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 10)
    return (
        "PASS" if ok else "FAIL",
        "Python >= 3.10",
        f"Python {v.major}.{v.minor}.{v.micro}",
        "Install Python 3.10+: https://python.org/downloads",
    )


def _check_demoparser2() -> tuple[str, str, str, str]:
    """Check that demoparser2 + pyogg are installed (replaces csgove in v0.1)."""
    try:
        importlib.import_module("demoparser2")
    except ImportError:
        return ("FAIL", "demoparser2", "Not installed", "Run: pip install demoparser2")
    try:
        importlib.import_module("pyogg")
        return ("PASS", "demoparser2 + pyogg", "Installed (voice extraction)", "")
    except ImportError:
        return ("FAIL", "pyogg", "Not installed", "Run: pip install pyogg")


def _check_csgove(interactive: bool = True) -> tuple[str, str, str, str]:
    """Check for csgove binary; offer auto-download if missing."""
    binary = "csgove.exe" if sys.platform == "win32" else "csgove"

    # Check PATH first
    path_found = shutil.which(binary)
    if path_found:
        return ("PASS", "csgove", f"Found at {path_found}", "")

    # Check local data dir
    from cs2tl.config import default_data_dir
    local_bin = default_data_dir() / "bin" / binary
    if local_bin.exists():
        return ("PASS", "csgove", f"Found at {local_bin}", "")

    # Offer auto-download
    if interactive:
        try:
            answer = input(
                "\ncsgove 未找到。是否自动下载到 cs2tl-data/bin/？[Y/n] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer and answer != "y":
            return ("WARN", "csgove", "Not found",
                    "Download manually: https://github.com/akiver/csgo-voice-extractor/releases/latest")
    else:
        answer = "y"

    if answer == "y" or answer == "":
        try:
            from cs2tl.cli.csgove_download import download_csgove
            path = download_csgove()
            return ("PASS", "csgove", f"Downloaded to {path}", "")
        except Exception as e:
            return ("WARN", "csgove", f"Download failed: {e}",
                    "Download manually: https://github.com/akiver/csgo-voice-extractor/releases/latest")

    return ("WARN", "csgove", "Not found",
            "Download: https://github.com/akiver/csgo-voice-extractor/releases/latest")


def _check_whisper() -> tuple[str, str, str, str]:
    try:
        importlib.import_module("faster_whisper")
        return ("PASS", "faster-whisper", "Installed", "")
    except ImportError:
        return ("FAIL", "faster-whisper", "Not installed", "Run: pip install faster-whisper")


def _check_awpy() -> tuple[str, str, str, str]:
    try:
        importlib.import_module("awpy")
        return ("PASS", "awpy", "Installed", "")
    except ImportError:
        return ("WARN", "awpy", "Not installed (player names + rounds unavailable)", "Run: pip install awpy")


def _check_openai() -> tuple[str, str, str, str]:
    try:
        importlib.import_module("openai")
        return ("PASS", "openai", "Installed", "")
    except ImportError:
        return ("FAIL", "openai", "Not installed", "Run: pip install openai")


def _check_git() -> tuple[str, str, str, str]:
    git = shutil.which("git")
    if git:
        return ("PASS", "git", str(git), "")
    return ("WARN", "git", "Not found on PATH (dictionary update unavailable)", "Install: https://git-scm.com")


def _check_config() -> tuple[str, str, str, str]:
    from cs2tl.config import default_config_path
    if default_config_path().exists():
        return ("PASS", "Config file", str(default_config_path()), "")
    return ("WARN", "Config file", "Not created yet", "Run: cs2tl config init")
