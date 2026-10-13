"""Run the loopback lab; live planning is opt-in through explicit configuration."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uvicorn


def port_free(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Port {port} is already in use. Stop that service before starting this lab.")


def main():
    os.chdir(Path(__file__).resolve().parent)
    for port in (8000, 8001):
        port_free(port)
    demo = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.demo:app", "--host", "127.0.0.1", "--port", "8001"])
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if demo.poll() is not None:
                raise SystemExit("The demo target failed to start. See the terminal error above.")
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", 8001)) == 0:
                    break
            time.sleep(0.1)
        else:
            raise SystemExit("The demo did not become ready within 10 seconds.")
        uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=8000, workers=1)
    finally:
        demo.terminate()
        try:
            demo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo.kill()
            demo.wait()


if __name__ == "__main__":
    main()
