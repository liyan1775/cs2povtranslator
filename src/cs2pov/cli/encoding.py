from __future__ import annotations

import os
import sys


def configure_utf8_stdio() -> None:
    """Prefer UTF-8 CLI output on Windows and in redirected logs.

    Windows Python may default to the active code page when a command is run
    directly instead of through the provided UTF-8 .bat launcher.  That makes
    feedback files such as doctor.txt/config_show.txt become GBK/ANSI encoded,
    while progress.log is UTF-8.  Force UTF-8 here so user-facing diagnostics
    are consistent and safe to zip/share.
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
