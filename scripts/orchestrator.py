from __future__ import annotations

import signal
import sys
import time

from apps.api.app.config import settings
from apps.api.app.services.background_tasks import process_pending_background_tasks

RUNNING = True


def _shutdown(_signum, _frame) -> None:
    global RUNNING
    RUNNING = False


def main() -> int:
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while RUNNING:
        processed = process_pending_background_tasks(limit=1)
        if processed > 0:
            time.sleep(0.5)
            continue
        time.sleep(max(1.0, settings.orchestrator_poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
