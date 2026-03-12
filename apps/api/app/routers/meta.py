from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.app.db import get_session
from apps.api.app.schemas import DashboardResponse
from apps.api.app.services.background_tasks import list_background_tasks
from apps.api.app.services.health import worker_readiness
from apps.api.app.services.saved_searches import (
    list_discovery_runs,
    list_saved_search_matches,
    list_saved_searches,
    sync_default_saved_search,
)
from apps.api.app.services.storage import (
    get_latest_profile,
    get_search_preferences,
    list_applications,
    list_jobs,
    list_profile_sources,
    list_worker_runs,
)

router = APIRouter(tags=["meta"])


@router.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/health/worker")
def worker_healthcheck(session: Session = Depends(get_session)) -> dict[str, object]:
    return worker_readiness(session)


@router.get("/api/dashboard", response_model=DashboardResponse)
def dashboard(session: Session = Depends(get_session)) -> DashboardResponse:
    profile = get_latest_profile(session)
    if profile is not None:
        sync_default_saved_search(session, profile, get_search_preferences(profile))
        session.commit()
    return DashboardResponse(
        profile=profile,
        profile_sources=list_profile_sources(session),
        jobs=list_jobs(session),
        applications=list_applications(session),
        worker_runs=list_worker_runs(session),
        saved_searches=list_saved_searches(session, profile.id) if profile is not None else [],
        discovery_runs=list_discovery_runs(session),
        saved_search_matches=list_saved_search_matches(session),
        background_tasks=list_background_tasks(session),
    )
