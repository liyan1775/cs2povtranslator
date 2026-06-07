"""Runner: starts uvicorn in a thread, runs Playwright acceptance tests."""
import sys
import time
import socket
import threading


def start_server():
    """Start uvicorn in a background thread."""
    import uvicorn
    from cs2tl.web.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)

    def run():
        server.run()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return server, t


def wait_for_server(host: str, port: int, timeout: int) -> bool:
    """Poll until the server accepts TCP connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


def main():
    print("Starting uvicorn server in thread...")
    server, thread = start_server()

    print("Waiting for server to be ready...")
    if not wait_for_server("127.0.0.1", 8765, 30):
        print("ERROR: Server failed to start within 30 seconds!")
        sys.exit(1)

    print("Server is ready. Running Playwright acceptance tests...\n")

    # Run the Playwright tests as a subprocess
    import subprocess
    result = subprocess.run(
        [sys.executable, "tests/acceptance_test.py"],
        timeout=600,
    )

    print(f"\nAcceptance tests finished with exit code: {result.returncode}")
    server.should_exit = True
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
