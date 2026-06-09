"""Doctor — dependency check command."""

from __future__ import annotations

import importlib
import io
import shutil
import sys

from rich.console import Console
from rich.table import Table


def _fix_windows_encoding() -> None:
    """Wrap stdout/stderr in UTF-8 on Windows terminals that default to GBK."""
    if sys.platform == "win32":
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name)
            if hasattr(stream, "buffer") and stream.encoding.lower() in (
                "gbk", "cp936", "cp1252",
            ):
                try:
                    setattr(
                        sys,
                        stream_name,
                        io.TextIOWrapper(
                            stream.buffer, encoding="utf-8", errors="replace"
                        ),
                    )
                except Exception:
                    pass


def doctor_cmd(verbose: bool = False) -> int:
    """Check all external dependencies and report status.

    Returns exit code: 0 if all checks pass, 1 if any fail.
    """
    _fix_windows_encoding()
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
        _check_whisper(),
        _check_awpy(),
        _check_openai(),
        _check_git(),
        *([_check_config()] if verbose else []),
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
