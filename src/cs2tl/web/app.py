"""FastAPI application for CS2 POV Translator Web UI.

Provides a browser-based interface for importing CS2 demos, running the
translation pipeline, previewing and editing translations, managing the
glossary, and exporting bilingual SRT subtitles.

Launch via: cs2tl web   (or: python -m cs2tl.web.app)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

# Set HF_HOME BEFORE any module that might trigger faster_whisper import.
# Must happen at module level because routes.py imports the config/transcriber
# chain, and faster_whisper reads HF_HOME on first import.
from cs2tl.config import default_data_dir

_hf_dir = str(default_data_dir() / "huggingface")
os.environ.setdefault("HF_HOME", _hf_dir)

from cs2tl.web.routes import job_store, router


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 — required by FastAPI
    """Startup: load persisted job history.  Shutdown: no-op (store flushes on every write)."""
    job_store.load()
    yield


app = FastAPI(
    title="CS2 POV Translator",
    version="0.2.0",
    description="CS2 Faceit demo voice comms → Chinese SRT subtitles",
    lifespan=lifespan,
)

app.include_router(router)


def main(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Launch the web server.

    Args:
        host: Bind address (default: 127.0.0.1 for local-only access).
        port: Bind port (default: 8765).
        open_browser: Whether to open the default browser on startup.
    """
    import webbrowser

    import uvicorn

    if open_browser:
        webbrowser.open(f"http://{host}:{port}")

    uvicorn.run(app, host=host, port=port, log_level="info")
