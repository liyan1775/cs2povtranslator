"""CS2 POV Translator — Windows Launcher (v0.1).

Double-click this file or run: python launch-cs2tl.py

Starts the web server and opens your browser. The server runs in the
background — close this window or press Ctrl+C to stop.

Why this instead of a .bat file?
  This approach works 100% on Windows because it runs uvicorn in-process
  rather than in a separate cmd window (which can fail to bind the port).

Requirements:
  pip install -e .    (installs cs2tl + all dependencies)
"""

import sys
import time
import socket
import threading
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def start_server():
    """Start uvicorn in a daemon thread — proven reliable on Windows."""
    import uvicorn
    from cs2tl.web.app import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)

    def run():
        server.run()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return server, t


def wait_until_ready(timeout: int = 60) -> bool:
    """Poll until the server accepts TCP connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((HOST, PORT), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def main():
    print("=" * 52)
    print("  CS2 POV Translator v0.1")
    print("  CS2 Faceit demo voice → Chinese SRT subtitles")
    print("=" * 52)
    print()

    # Ensure we're in the project root (where dictionaries/ lives)
    project_root = Path(__file__).resolve().parent
    # We don't need to cd — just make sure the package is importable

    print("Starting server...")
    server, thread = start_server()

    print("Waiting for server...", end="", flush=True)
    if not wait_until_ready():
        print()
        print()
        print("❌ Server failed to start within 60 seconds.")
        print()
        print("Try running this instead:")
        print("  pip install -e .")
        print("  cs2tl web")
        input("Press Enter to exit...")
        return 1

    print(f" ready!")
    print(f"Opening browser: {URL}/import")
    print()

    webbrowser.open(f"{URL}/import")

    print("=" * 52)
    print("  Server running at " + URL)
    print("  Press Ctrl+C or close this window to stop.")
    print("=" * 52)

    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        print("Shutting down...")
        server.should_exit = True
        thread.join(timeout=5)

    return 0


if __name__ == "__main__":
    sys.exit(main())
