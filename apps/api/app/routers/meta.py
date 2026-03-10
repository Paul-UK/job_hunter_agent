from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_session
from apps.api.app.schemas import DashboardResponse
from apps.api.app.services.storage import (
    get_latest_profile,
    list_applications,
    list_jobs,
    list_profile_sources,
    list_worker_runs,
)

router = APIRouter(tags=["meta"])


@router.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/dashboard", response_model=DashboardResponse)
def dashboard(session: Session = Depends(get_session)) -> DashboardResponse:
    return DashboardResponse(
        profile=get_latest_profile(session),
        profile_sources=list_profile_sources(session),
        jobs=list_jobs(session),
        applications=list_applications(session),
        worker_runs=list_worker_runs(session),
    )
