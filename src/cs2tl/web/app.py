"""FastAPI application for CS2 POV Translator Web UI.

Provides a browser-based interface for importing CS2 demos, running the
translation pipeline, previewing and editing translations, managing the
glossary, and exporting bilingual SRT subtitles.

Launch via: cs2tl web   (or: python -m cs2tl.web.app)
"""

from pathlib import Path

from fastapi import FastAPI

from cs2tl.web.routes import router

app = FastAPI(
    title="CS2 POV Translator",
    version="0.1.0",
    description="CS2 Faceit demo voice comms → Chinese SRT subtitles",
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
