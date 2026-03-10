from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db import get_session
from apps.api.app.models import ApplicationDraft, WorkerRun
from apps.api.app.schemas import (
    ApplicationDraftResponse,
    ApplicationDraftWorkerPayload,
    ApplicationRunRequest,
    JobLeadWorkerPayload,
    WorkerRunRequest,
    WorkerRunResponse,
)
from apps.api.app.services.storage import (
    get_latest_profile,
    get_profile_payload,
    list_applications,
    list_worker_runs,
)
from apps.worker.main import run_worker

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationDraftResponse])
def read_applications(session: Session = Depends(get_session)) -> list[ApplicationDraftResponse]:
    return list_applications(session)


@router.get("/runs", response_model=list[WorkerRunResponse])
def read_worker_runs(session: Session = Depends(get_session)) -> list[WorkerRunResponse]:
    return list_worker_runs(session)


@router.post("/{application_id}/run", response_model=WorkerRunResponse)
def run_application(
    application_id: int,
    payload: ApplicationRunRequest,
    session: Session = Depends(get_session),
) -> WorkerRunResponse:
    draft = session.execute(
        select(ApplicationDraft).where(ApplicationDraft.id == application_id)
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(status_code=404, detail="Application draft not found.")

    profile = get_latest_profile(session)
    profile_payload = get_profile_payload(profile)
    if profile is None or profile_payload is None:
        raise HTTPException(
            status_code=400, detail="Profile data is required before running the worker."
        )

    job = draft.job_lead
    if job is None:
        raise HTTPException(
            status_code=400, detail="Application draft is missing a linked job lead."
        )

    if payload.cover_note is not None:
        draft.cover_note = payload.cover_note
    if payload.screening_answers is not None:
        draft.screening_answers = [answer.model_dump(mode="json") for answer in payload.screening_answers]

    draft_payload = ApplicationDraftWorkerPayload(
        tailored_summary=draft.tailored_summary,
        cover_note=draft.cover_note,
        resume_bullets=draft.resume_bullets,
        screening_answers=draft.screening_answers,
    )
    job_payload = JobLeadWorkerPayload(
        source=job.source,
        company=job.company,
        title=job.title,
        location=job.location,
        employment_type=job.employment_type,
        url=job.url,
        description=job.description,
        requirements=job.requirements,
        metadata_json=job.metadata_json,
    )
    worker_request = WorkerRunRequest(
        application_draft_id=draft.id,
        target_url=job.url,
        platform=job.source if job.source in {"greenhouse", "lever"} else "generic",
        profile=profile_payload,
        job=job_payload,
        draft=draft_payload,
        answer_overrides=payload.answer_overrides,
        dry_run=payload.dry_run,
        confirm_submit=payload.confirm_submit,
        fixture_html=payload.fixture_html,
    )

    result = run_worker(worker_request)
    worker_run = WorkerRun(
        application_draft_id=draft.id,
        platform=result["platform"],
        target_url=result["target_url"],
        dry_run=result["dry_run"],
        status=result["status"],
        actions=result["actions"],
        logs=result["logs"],
        fields=result["fields"],
        review_items=result["review_items"],
        preview_summary=result["preview_summary"],
        profile_snapshot=result["profile_snapshot"],
        job_snapshot=result["job_snapshot"],
        draft_snapshot=result["draft_snapshot"],
        screenshot_path=result["screenshot_path"],
    )
    draft.status = result["status"]
    session.add(worker_run)
    session.commit()
    session.refresh(worker_run)
    return worker_run
