from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_session
from apps.api.app.models import JobLead, SavedSearchMatch
from apps.api.app.schemas import (
    BackgroundTaskResponse,
    SavedSearchCreateRequest,
    SavedSearchMatchFeedbackRequest,
    SavedSearchMatchResponse,
    SavedSearchResponse,
    SavedSearchUpdateRequest,
)
from apps.api.app.services.background_tasks import enqueue_discovery_task
from apps.api.app.services.saved_searches import (
    apply_match_feedback,
    create_saved_search,
    delete_saved_search,
    get_saved_search,
    list_saved_searches,
    sync_default_saved_search,
    update_saved_search,
    upsert_saved_search_match,
)
from apps.api.app.services.storage import (
    get_latest_profile,
    get_profile_payload,
    get_search_preferences,
    rerank_all_jobs,
)

router = APIRouter(prefix="/api/searches", tags=["searches"])


@router.get("", response_model=list[SavedSearchResponse])
def read_saved_searches(session: Session = Depends(get_session)) -> list[SavedSearchResponse]:
    profile = get_latest_profile(session)
    if profile is None:
        return []
    sync_default_saved_search(session, profile, get_search_preferences(profile))
    session.commit()
    return list_saved_searches(session, profile.id)


@router.post("", response_model=SavedSearchResponse)
def create_search(
    payload: SavedSearchCreateRequest,
    session: Session = Depends(get_session),
) -> SavedSearchResponse:
    profile = get_latest_profile(session)
    if profile is None:
        raise HTTPException(status_code=400, detail="Upload or review your profile before saving searches.")
    saved_search = create_saved_search(
        session,
        profile=profile,
        name=payload.name,
        search_preferences=payload.search_preferences,
        enabled=payload.enabled,
        cadence_minutes=payload.cadence_minutes,
    )
    session.commit()
    session.refresh(saved_search)
    return saved_search


@router.put("/{search_id}", response_model=SavedSearchResponse)
def update_search(
    search_id: int,
    payload: SavedSearchUpdateRequest,
    session: Session = Depends(get_session),
) -> SavedSearchResponse:
    saved_search = get_saved_search(session, search_id)
    if saved_search is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")
    if saved_search.is_default and payload.enabled is False:
        raise HTTPException(status_code=400, detail="The default saved search cannot be disabled.")

    updated_search = update_saved_search(
        session,
        saved_search,
        name=payload.name,
        search_preferences=payload.search_preferences,
        enabled=payload.enabled,
        cadence_minutes=payload.cadence_minutes,
    )
    if updated_search.is_default and payload.search_preferences is not None:
        profile = updated_search.profile
        if profile is not None:
            profile.search_preferences = updated_search.search_preferences
            profile.search_preferences_customized = True
            profile_payload = get_profile_payload(profile)
            if profile_payload is not None:
                rerank_all_jobs(session, profile_payload, payload.search_preferences)
    session.commit()
    session.refresh(updated_search)
    return updated_search


@router.delete("/{search_id}")
def remove_search(search_id: int, session: Session = Depends(get_session)) -> dict[str, int]:
    saved_search = get_saved_search(session, search_id)
    if saved_search is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")
    if saved_search.is_default:
        raise HTTPException(status_code=400, detail="The default saved search cannot be deleted.")
    delete_saved_search(session, saved_search)
    session.commit()
    return {"deleted_id": search_id}


@router.post("/{search_id}/run", response_model=BackgroundTaskResponse)
def run_saved_search(search_id: int, session: Session = Depends(get_session)) -> BackgroundTaskResponse:
    saved_search = get_saved_search(session, search_id)
    if saved_search is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")
    profile = saved_search.profile
    profile_payload = get_profile_payload(profile)
    if profile is None or profile_payload is None:
        raise HTTPException(
            status_code=400,
            detail="Upload or review your profile before running a saved search.",
        )
    task, _run = enqueue_discovery_task(
        session,
        saved_search=saved_search,
        profile=profile,
        trigger_kind="manual",
    )
    session.commit()
    session.refresh(task)
    return task


@router.post("/{search_id}/matches/{job_id}/feedback", response_model=SavedSearchMatchResponse)
def save_search_feedback(
    search_id: int,
    job_id: int,
    payload: SavedSearchMatchFeedbackRequest,
    session: Session = Depends(get_session),
) -> SavedSearchMatchResponse:
    saved_search = get_saved_search(session, search_id)
    if saved_search is None:
        raise HTTPException(status_code=404, detail="Saved search not found.")

    match = session.execute(
        select(SavedSearchMatch).where(
            SavedSearchMatch.saved_search_id == search_id,
            SavedSearchMatch.job_lead_id == job_id,
        )
    ).scalar_one_or_none()
    if match is None:
        job = session.execute(select(JobLead).where(JobLead.id == job_id)).scalar_one_or_none()
        profile_payload = get_profile_payload(saved_search.profile)
        if job is None:
            raise HTTPException(status_code=404, detail="Job lead not found.")
        if profile_payload is None:
            raise HTTPException(status_code=400, detail="Profile data is required before recording feedback.")
        match = upsert_saved_search_match(
            session,
            saved_search=saved_search,
            job=job,
            profile_payload=profile_payload,
        )

    apply_match_feedback(session, match=match, signal=payload.signal, note=payload.note)
    session.commit()
    session.refresh(match)
    return match
