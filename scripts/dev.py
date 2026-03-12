from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_CMD = [
    "uv",
    "run",
    "uvicorn",
    "apps.api.app.main:app",
    "--reload",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
]
ORCHESTRATOR_CMD = ["uv", "run", "python", "scripts/orchestrator.py"]
WEB_CMD = ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


def main() -> int:
    api = subprocess.Popen(API_CMD, cwd=ROOT)
    orchestrator = subprocess.Popen(ORCHESTRATOR_CMD, cwd=ROOT)
    web = subprocess.Popen(WEB_CMD, cwd=ROOT / "apps" / "web")
    children = [api, orchestrator, web]

    def shutdown(_signum, _frame):
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    exit_code = 0
    for child in children:
        return_code = child.wait()
        if return_code != 0:
            exit_code = return_code
            shutdown(signal.SIGTERM, None)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
