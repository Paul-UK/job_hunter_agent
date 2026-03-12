from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import settings
from apps.api.app.models import (
    BackgroundTask,
    CandidateProfile,
    DiscoveryRun,
    JobLead,
    SavedSearch,
    SavedSearchMatch,
    SearchFeedbackEvent,
)
from apps.api.app.schemas import CandidateProfilePayload, SearchPreferencesPayload
from apps.api.app.services.matching import rank_job
from apps.api.app.services.search_preferences import normalize_search_preferences

DEFAULT_SAVED_SEARCH_NAME = "Default search"
FEEDBACK_SCORE_ADJUSTMENTS = {
    "neutral": 0.0,
    "shortlisted": 12.0,
    "drafted": 18.0,
    "applied": 24.0,
    "dismissed": -50.0,
}


def list_saved_searches(session: Session, profile_id: int | None = None) -> list[SavedSearch]:
    if profile_id is None:
        return []
    statement = select(SavedSearch)
    statement = statement.where(SavedSearch.profile_id == profile_id)
    statement = statement.order_by(SavedSearch.is_default.desc(), SavedSearch.id.asc())
    return list(session.execute(statement).scalars())


def get_saved_search(session: Session, search_id: int) -> SavedSearch | None:
    return session.execute(select(SavedSearch).where(SavedSearch.id == search_id)).scalar_one_or_none()


def get_default_saved_search(session: Session, profile_id: int | None) -> SavedSearch | None:
    if profile_id is None:
        return None
    return session.execute(
        select(SavedSearch)
        .where(SavedSearch.profile_id == profile_id, SavedSearch.is_default.is_(True))
        .order_by(SavedSearch.id.asc())
        .limit(1)
    ).scalar_one_or_none()


def sync_default_saved_search(
    session: Session,
    profile: CandidateProfile,
    search_preferences: SearchPreferencesPayload,
) -> SavedSearch:
    normalized_preferences = normalize_search_preferences(search_preferences)
    saved_search = get_default_saved_search(session, profile.id)
    now = datetime.now(UTC)
    if saved_search is None:
        saved_search = SavedSearch(
            profile_id=profile.id,
            name=DEFAULT_SAVED_SEARCH_NAME,
            search_preferences=normalized_preferences.model_dump(mode="json"),
            enabled=True,
            is_default=True,
            cadence_minutes=settings.default_search_cadence_minutes,
            next_run_at=now,
            last_status="idle",
        )
        session.add(saved_search)
        session.flush()
        return saved_search

    saved_search.search_preferences = normalized_preferences.model_dump(mode="json")
    if saved_search.next_run_at is None:
        saved_search.next_run_at = now
    if not saved_search.name.strip():
        saved_search.name = DEFAULT_SAVED_SEARCH_NAME
    return saved_search


def create_saved_search(
    session: Session,
    *,
    profile: CandidateProfile,
    name: str,
    search_preferences: SearchPreferencesPayload,
    enabled: bool,
    cadence_minutes: int,
) -> SavedSearch:
    saved_search = SavedSearch(
        profile_id=profile.id,
        name=name.strip(),
        search_preferences=normalize_search_preferences(search_preferences).model_dump(mode="json"),
        enabled=enabled,
        cadence_minutes=cadence_minutes,
        next_run_at=datetime.now(UTC),
        last_status="idle",
    )
    session.add(saved_search)
    session.flush()
    return saved_search


def update_saved_search(
    session: Session,
    saved_search: SavedSearch,
    *,
    name: str | None = None,
    search_preferences: SearchPreferencesPayload | None = None,
    enabled: bool | None = None,
    cadence_minutes: int | None = None,
) -> SavedSearch:
    if name is not None:
        saved_search.name = name.strip()
    if search_preferences is not None:
        saved_search.search_preferences = normalize_search_preferences(search_preferences).model_dump(
            mode="json"
        )
    if enabled is not None:
        saved_search.enabled = enabled
    if cadence_minutes is not None:
        saved_search.cadence_minutes = cadence_minutes
    if saved_search.enabled and saved_search.next_run_at is None:
        saved_search.next_run_at = datetime.now(UTC)
    return saved_search


def delete_saved_search(session: Session, saved_search: SavedSearch) -> None:
    matches = session.execute(
        select(SavedSearchMatch).where(SavedSearchMatch.saved_search_id == saved_search.id)
    ).scalars().all()
    match_ids = [match.id for match in matches]
    if match_ids:
        feedback_events = session.execute(
            select(SearchFeedbackEvent).where(SearchFeedbackEvent.saved_search_match_id.in_(match_ids))
        ).scalars().all()
        for event in feedback_events:
            session.delete(event)
    for match in matches:
        session.delete(match)

    discovery_runs = session.execute(
        select(DiscoveryRun).where(DiscoveryRun.saved_search_id == saved_search.id)
    ).scalars().all()
    for run in discovery_runs:
        tasks = session.execute(
            select(BackgroundTask).where(BackgroundTask.discovery_run_id == run.id)
        ).scalars().all()
        for task in tasks:
            session.delete(task)
        session.delete(run)

    tasks = session.execute(
        select(BackgroundTask).where(BackgroundTask.saved_search_id == saved_search.id)
    ).scalars().all()
    for task in tasks:
        session.delete(task)

    session.delete(saved_search)


def list_discovery_runs(session: Session, limit: int = 25) -> list[DiscoveryRun]:
    return list(
        session.execute(
            select(DiscoveryRun)
            .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
            .limit(limit)
        ).scalars()
    )


def list_saved_search_matches(
    session: Session,
    *,
    search_id: int | None = None,
) -> list[SavedSearchMatch]:
    statement = select(SavedSearchMatch).order_by(
        SavedSearchMatch.current_score.desc().nullslast(),
        SavedSearchMatch.updated_at.desc(),
        SavedSearchMatch.id.desc(),
    )
    if search_id is not None:
        statement = statement.where(SavedSearchMatch.saved_search_id == search_id)
    return list(session.execute(statement).scalars())


def upsert_saved_search_match(
    session: Session,
    *,
    saved_search: SavedSearch,
    job: JobLead,
    profile_payload: CandidateProfilePayload,
    discovery_run: DiscoveryRun | None = None,
) -> SavedSearchMatch:
    existing = session.execute(
        select(SavedSearchMatch).where(
            SavedSearchMatch.saved_search_id == saved_search.id,
            SavedSearchMatch.job_lead_id == job.id,
        )
    ).scalar_one_or_none()
    normalized_preferences = normalize_search_preferences(saved_search.search_preferences)
    ranking = rank_job(profile_payload, _job_to_payload(job), normalized_preferences)
    feedback_state = existing.feedback_state if existing is not None else "neutral"
    adjusted_score = _apply_feedback_adjustment(ranking.score, feedback_state)
    score_details = ranking.model_dump(mode="json")
    score_details.update(
        {
            "base_score": ranking.score,
            "feedback_state": feedback_state,
            "feedback_adjustment": round(adjusted_score - ranking.score, 2),
            "saved_search_name": saved_search.name,
        }
    )
    now = datetime.now(UTC)
    if existing is None:
        existing = SavedSearchMatch(
            saved_search_id=saved_search.id,
            job_lead_id=job.id,
            discovery_run_id=discovery_run.id if discovery_run is not None else None,
            current_score=adjusted_score,
            score_details=score_details,
            feedback_state=feedback_state,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(existing)
        session.flush()
        return existing

    existing.discovery_run_id = discovery_run.id if discovery_run is not None else existing.discovery_run_id
    existing.current_score = adjusted_score
    existing.score_details = score_details
    existing.last_seen_at = now
    return existing


def rerank_saved_search_matches(
    session: Session,
    *,
    profile_payload: CandidateProfilePayload,
    saved_searches: list[SavedSearch],
) -> None:
    if not saved_searches:
        return
    search_ids = [saved_search.id for saved_search in saved_searches]
    matches = session.execute(
        select(SavedSearchMatch).where(SavedSearchMatch.saved_search_id.in_(search_ids))
    ).scalars().all()
    searches_by_id = {saved_search.id: saved_search for saved_search in saved_searches}
    jobs_by_id = {
        job.id: job
        for job in session.execute(
            select(JobLead).where(JobLead.id.in_({match.job_lead_id for match in matches}))
        ).scalars()
    }
    for match in matches:
        saved_search = searches_by_id.get(match.saved_search_id)
        job = jobs_by_id.get(match.job_lead_id)
        if saved_search is None or job is None:
            continue
        normalized_preferences = normalize_search_preferences(saved_search.search_preferences)
        ranking = rank_job(profile_payload, _job_to_payload(job), normalized_preferences)
        match.current_score = _apply_feedback_adjustment(ranking.score, match.feedback_state)
        score_details = ranking.model_dump(mode="json")
        score_details.update(
            {
                "base_score": ranking.score,
                "feedback_state": match.feedback_state,
                "feedback_adjustment": round(match.current_score - ranking.score, 2),
                "saved_search_name": saved_search.name,
            }
        )
        match.score_details = score_details


def apply_match_feedback(
    session: Session,
    *,
    match: SavedSearchMatch,
    signal: str,
    note: str | None = None,
) -> SavedSearchMatch:
    match.feedback_state = signal
    match.feedback_note = (note or "").strip() or None
    match.last_feedback_at = datetime.now(UTC)

    base_score = float(match.score_details.get("base_score") or match.current_score or 0.0)
    match.current_score = _apply_feedback_adjustment(base_score, signal)
    updated_score_details = dict(match.score_details or {})
    updated_score_details["feedback_state"] = signal
    updated_score_details["feedback_adjustment"] = round(match.current_score - base_score, 2)
    match.score_details = updated_score_details

    session.add(
        SearchFeedbackEvent(
            saved_search_match_id=match.id,
            signal=signal,
            note=match.feedback_note,
        )
    )
    return match


def apply_feedback_for_job(
    session: Session,
    *,
    job_id: int,
    signal: str,
    note: str | None = None,
) -> list[SavedSearchMatch]:
    matches = session.execute(
        select(SavedSearchMatch).where(SavedSearchMatch.job_lead_id == job_id)
    ).scalars().all()
    for match in matches:
        apply_match_feedback(session, match=match, signal=signal, note=note)
    return matches


def mark_saved_search_run_started(saved_search: SavedSearch) -> None:
    now = datetime.now(UTC)
    saved_search.last_status = "running"
    saved_search.last_error = None
    saved_search.last_run_at = now


def mark_saved_search_run_finished(
    saved_search: SavedSearch,
    *,
    status: str,
    error_message: str | None = None,
) -> None:
    now = datetime.now(UTC)
    saved_search.last_status = status
    saved_search.last_error = error_message
    saved_search.last_run_at = now
    if status == "completed":
        saved_search.last_success_at = now
    saved_search.next_run_at = now + timedelta(minutes=max(15, saved_search.cadence_minutes))


def _apply_feedback_adjustment(score: float, feedback_state: str) -> float:
    adjustment = FEEDBACK_SCORE_ADJUSTMENTS.get(feedback_state, 0.0)
    return round(max(0.0, min(100.0, score + adjustment)), 2)


def _job_to_payload(job: JobLead) -> dict:
    return {
        "source": job.source,
        "external_id": job.external_id,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "employment_type": job.employment_type,
        "url": job.url,
        "description": job.description,
        "requirements": job.requirements,
        "metadata_json": job.metadata_json,
    }
