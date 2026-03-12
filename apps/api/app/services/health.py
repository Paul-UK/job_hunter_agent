from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.config import settings
from apps.api.app.db import engine
from apps.api.app.models import BackgroundTask


def worker_readiness(session: Session) -> dict[str, object]:
    database_ok = _check_database()
    chromium_path, chromium_installed = _check_chromium_install()
    uploads_dir = settings.data_dir / "uploads"
    queued_tasks = session.execute(
        select(func.count(BackgroundTask.id)).where(BackgroundTask.status == "queued")
    ).scalar_one()
    running_tasks = session.execute(
        select(func.count(BackgroundTask.id)).where(BackgroundTask.status == "running")
    ).scalar_one()
    checks = {
        "database_ok": database_ok,
        "data_dir_exists": settings.data_dir.exists(),
        "artifacts_dir_exists": settings.artifacts_dir.exists(),
        "uploads_dir_exists": uploads_dir.exists(),
        "chromium_installed": chromium_installed,
    }
    return {
        "status": "ok" if all(bool(value) for value in checks.values()) else "degraded",
        "checks": checks,
        "chromium_path": chromium_path,
        "queued_tasks": int(queued_tasks or 0),
        "running_tasks": int(running_tasks or 0),
    }


def _check_database() -> bool:
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False


def _check_chromium_install() -> tuple[str | None, bool]:
    try:
        with sync_playwright() as playwright:
            executable_path = Path(playwright.chromium.executable_path)
            return str(executable_path), executable_path.exists()
    except (PlaywrightError, OSError):
        return None, False
