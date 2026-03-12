from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_session
from apps.api.app.schemas import BackgroundTaskResponse
from apps.api.app.services.background_tasks import list_background_tasks, process_pending_background_tasks

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[BackgroundTaskResponse])
def read_background_tasks(session: Session = Depends(get_session)) -> list[BackgroundTaskResponse]:
    return list_background_tasks(session)


@router.post("/process")
def process_background_task_queue(limit: int = 1) -> dict[str, int]:
    processed = process_pending_background_tasks(limit=max(1, min(limit, 10)), include_scheduled=False)
    return {"processed": processed}
