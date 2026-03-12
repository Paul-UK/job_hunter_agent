from __future__ import annotations

from datetime import UTC, datetime
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_session
from apps.api.app.models import ApplicationDraft, JobLead
from apps.api.app.schemas import (
    ApplicationDraftResponse,
    BulkDeleteResponse,
    DeleteResponse,
    JobDiscoveryRequest,
    JobLeadCrmUpdateRequest,
    JobLeadBulkDeleteRequest,
    JobLeadResponse,
    LinkedinLeadRequest,
    ResearchResponse,
    WebJobDiscoveryRequest,
    WebJobDiscoveryResponse,
)
from apps.api.app.services.company_research import research_company
from apps.api.app.services.company_research import research_needs_refresh
from apps.api.app.services.drafting import build_application_draft
from apps.api.app.services.job_discovery import WebDiscoveryError, discover_jobs_from_web
from apps.api.app.services.job_sources.ashby import fetch_ashby_jobs
from apps.api.app.services.job_sources.greenhouse import fetch_greenhouse_jobs
from apps.api.app.services.job_sources.lever import fetch_lever_jobs
from apps.api.app.services.job_sources.linkedin import create_linkedin_lead
from apps.api.app.services.matching import rank_job
from apps.api.app.services.saved_searches import (
    apply_feedback_for_job,
    sync_default_saved_search,
    upsert_saved_search_match,
)
from apps.api.app.services.storage import (
    delete_job_lead,
    delete_job_leads,
    get_latest_profile,
    get_profile_payload,
    get_search_preferences,
    list_jobs,
    update_search_preferences,
    upsert_job_lead,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=list[JobLeadResponse])
def read_jobs(session: Session = Depends(get_session)) -> list[JobLeadResponse]:
    return list_jobs(session)


@router.post("/discover/greenhouse", response_model=list[JobLeadResponse])
def discover_greenhouse_jobs(
    payload: JobDiscoveryRequest,
    session: Session = Depends(get_session),
) -> list[JobLeadResponse]:
    discovered: list[JobLead] = []
    failures: list[tuple[int, str]] = []
    for board_token in payload.identifiers:
        try:
            jobs = fetch_greenhouse_jobs(
                board_token, include_questions=payload.include_questions
            )
        except Exception as exc:
            failures.append(_map_discovery_error("greenhouse", board_token, exc))
            continue

        for job_payload in jobs:
            discovered.append(_save_and_score_job(session, job_payload))

    _raise_if_discovery_failed(failures, discovered)
    return discovered


@router.post("/discover/lever", response_model=list[JobLeadResponse])
def discover_lever_jobs(
    payload: JobDiscoveryRequest,
    session: Session = Depends(get_session),
) -> list[JobLeadResponse]:
    discovered: list[JobLead] = []
    failures: list[tuple[int, str]] = []
    for slug in payload.identifiers:
        try:
            jobs = fetch_lever_jobs(slug)
        except Exception as exc:
            failures.append(_map_discovery_error("lever", slug, exc))
            continue

        for job_payload in jobs:
            discovered.append(_save_and_score_job(session, job_payload))

    _raise_if_discovery_failed(failures, discovered)
    return discovered


@router.post("/discover/ashby", response_model=list[JobLeadResponse])
def discover_ashby_jobs(
    payload: JobDiscoveryRequest,
    session: Session = Depends(get_session),
) -> list[JobLeadResponse]:
    discovered: list[JobLead] = []
    failures: list[tuple[int, str]] = []
    for job_board_name in payload.identifiers:
        try:
            jobs = fetch_ashby_jobs(job_board_name)
        except Exception as exc:
            failures.append(_map_discovery_error("ashbyhq", job_board_name, exc))
            continue

        for job_payload in jobs:
            discovered.append(_save_and_score_job(session, job_payload))

    _raise_if_discovery_failed(failures, discovered)
    return discovered


@router.post("/discover/linkedin", response_model=JobLeadResponse)
def discover_linkedin_job(
    payload: LinkedinLeadRequest,
    session: Session = Depends(get_session),
) -> JobLeadResponse:
    job = _save_and_score_job(session, create_linkedin_lead(payload))
    return job


@router.post("/discover/web", response_model=WebJobDiscoveryResponse)
def discover_web_jobs(
    payload: WebJobDiscoveryRequest,
    session: Session = Depends(get_session),
) -> WebJobDiscoveryResponse:
    profile = get_latest_profile(session)
    profile_payload = get_profile_payload(profile)
    if profile is None or profile_payload is None:
        raise HTTPException(
            status_code=400,
            detail="Upload or review your profile before using AI web discovery.",
        )

    profile = update_search_preferences(session, payload.search_preferences)
    search_preferences = get_search_preferences(profile)
    try:
        discovery_result = discover_jobs_from_web(
            profile=profile_payload,
            search_preferences=search_preferences,
        )
    except WebDiscoveryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    discovered = [_save_and_score_job(session, job_payload) for job_payload in discovery_result.jobs]
    return WebJobDiscoveryResponse(
        jobs=discovered,
        search_preferences=search_preferences,
        search_queries=discovery_result.search_queries,
        source_urls=discovery_result.source_urls,
        grounded_pages_count=discovery_result.grounded_pages_count,
    )


@router.post("/{job_id}/research", response_model=ResearchResponse)
def run_company_research(job_id: int, session: Session = Depends(get_session)) -> ResearchResponse:
    job = _get_job(session, job_id)
    research = research_company(job.company, job.url)
    job.research = research
    session.commit()
    session.refresh(job)
    return ResearchResponse(**research)


@router.post("/{job_id}/draft", response_model=ApplicationDraftResponse)
def draft_application(
    job_id: int, session: Session = Depends(get_session)
) -> ApplicationDraftResponse:
    job = _get_job(session, job_id)
    profile = get_latest_profile(session)
    profile_payload = get_profile_payload(profile)
    search_preferences = get_search_preferences(profile)
    if profile is None or profile_payload is None:
        raise HTTPException(status_code=400, detail="Upload a CV before drafting applications.")

    existing_draft = session.execute(
        select(ApplicationDraft)
        .where(ApplicationDraft.profile_id == profile.id, ApplicationDraft.job_lead_id == job.id)
        .limit(1)
    ).scalar_one_or_none()
    if existing_draft is not None:
        return existing_draft

    ranking = rank_job(profile_payload, job_to_payload(job), search_preferences)
    job.score = ranking.score
    job.score_details = ranking.model_dump(mode="json")
    if research_needs_refresh(job.research):
        job.research = research_company(job.company, job.url)

    draft_payload = build_application_draft(
        profile_payload,
        job_to_payload(job),
        ranking,
        job.research,
    )
    draft = ApplicationDraft(
        profile_id=profile.id,
        job_lead_id=job.id,
        tailored_summary=draft_payload["tailored_summary"],
        cover_note=draft_payload["cover_note"],
        resume_bullets=draft_payload["resume_bullets"],
        screening_answers=draft_payload["screening_answers"],
    )
    job.crm_stage = "drafted"
    session.add(draft)
    apply_feedback_for_job(session, job_id=job.id, signal="drafted")
    session.commit()
    session.refresh(draft)
    return draft


@router.patch("/{job_id}/crm", response_model=JobLeadResponse)
def update_job_crm(
    job_id: int,
    payload: JobLeadCrmUpdateRequest,
    session: Session = Depends(get_session),
) -> JobLeadResponse:
    job = _get_job(session, job_id)
    if payload.crm_stage is not None:
        job.crm_stage = payload.crm_stage
    if payload.crm_notes is not None:
        job.crm_notes = payload.crm_notes
    if payload.follow_up_at is not None:
        job.follow_up_at = payload.follow_up_at
    if payload.last_contacted_at is not None:
        job.last_contacted_at = payload.last_contacted_at
    if payload.is_active is not None:
        job.is_active = payload.is_active

    if job.crm_stage in {"rejected", "archived"} or job.is_active is False:
        job.is_active = False
        job.closed_at = job.closed_at or datetime.now(UTC)
    elif job.is_active:
        job.closed_at = None

    session.commit()
    session.refresh(job)
    return job


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
def bulk_remove_jobs(
    payload: JobLeadBulkDeleteRequest,
    session: Session = Depends(get_session),
) -> BulkDeleteResponse:
    if not payload.job_ids:
        raise HTTPException(status_code=400, detail="Provide at least one job ID to delete.")

    deleted_ids, deleted_counts = delete_job_leads(session, payload.job_ids)
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="No matching job leads were found.")
    return BulkDeleteResponse(
        entity="job_leads",
        deleted_ids=deleted_ids,
        deleted_counts=deleted_counts,
    )


@router.delete("/{job_id}", response_model=DeleteResponse)
def remove_job(job_id: int, session: Session = Depends(get_session)) -> DeleteResponse:
    deleted_counts = delete_job_lead(session, job_id)
    if deleted_counts is None:
        raise HTTPException(status_code=404, detail="Job lead not found.")
    return DeleteResponse(
        entity="job_lead",
        deleted_id=job_id,
        deleted_counts=deleted_counts,
    )


def _save_and_score_job(session: Session, payload: dict) -> JobLead:
    profile = get_latest_profile(session)
    profile_payload = get_profile_payload(profile)
    search_preferences = get_search_preferences(profile)
    job = upsert_job_lead(session, payload)
    if profile_payload and profile is not None:
        ranking = rank_job(profile_payload, payload, search_preferences)
        job.score = ranking.score
        job.score_details = ranking.model_dump(mode="json")
        default_search = sync_default_saved_search(session, profile, search_preferences)
        upsert_saved_search_match(
            session,
            saved_search=default_search,
            job=job,
            profile_payload=profile_payload,
        )
        session.commit()
        session.refresh(job)
    return job


def _get_job(session: Session, job_id: int) -> JobLead:
    job = session.execute(select(JobLead).where(JobLead.id == job_id)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job lead not found.")
    return job


def job_to_payload(job: JobLead) -> dict:
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


def _map_discovery_error(
    source: str, identifier: str, exc: Exception
) -> tuple[int, str]:
    source_label = _source_display_name(source)
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 404:
            if source == "greenhouse":
                return (
                    400,
                    f"Greenhouse board token '{identifier}' was not found. "
                    "Use the public board token from the company's Greenhouse URL.",
                )
            if source == "ashbyhq":
                return (
                    400,
                    f"Ashby job board '{identifier}' was not found. "
                    "Use the final path segment from jobs.ashbyhq.com/<job-board-name>.",
                )
            return (
                400,
                f"Lever company slug '{identifier}' was not found. "
                "Use the slug from jobs.lever.co/<company-slug>.",
            )
        if status_code == 429:
            return (
                503,
                f"{source_label} is rate limiting requests for '{identifier}'. "
                "Try again shortly.",
            )
        if 500 <= status_code < 600:
            return (
                502,
                f"{source_label} returned {status_code} while loading '{identifier}'.",
            )
        return (
            502,
            f"{source_label} returned {status_code} for '{identifier}'.",
        )

    if isinstance(exc, httpx.TimeoutException):
        return (
            504,
            f"{source_label} timed out while loading '{identifier}'. Try again in a moment.",
        )

    if isinstance(exc, httpx.RequestError):
        return (
            502,
            f"Could not reach {source_label} while loading '{identifier}'.",
        )

    logger.exception(
        "Unexpected %s discovery error for identifier %s",
        source,
        identifier,
        exc_info=exc,
    )
    return (
        500,
        f"Unexpected {source_label} discovery error for '{identifier}'.",
    )


def _source_display_name(source: str) -> str:
    if source == "ashbyhq":
        return "Ashby"
    return source.title()


def _raise_if_discovery_failed(
    failures: list[tuple[int, str]], discovered: list[JobLead]
) -> None:
    if not failures:
        return

    if discovered:
        logger.warning(
            "Discovery completed with partial failures: %s",
            "; ".join(message for _status, message in failures),
        )
        return

    status_code = max(status for status, _message in failures)
    detail = "; ".join(message for _status, message in failures)
    raise HTTPException(status_code=status_code, detail=detail)
