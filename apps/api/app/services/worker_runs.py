from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from apps.api.app.models import ApplicationDraft, JobLead, WorkerRun
from apps.api.app.schemas import (
    ApplicationDraftWorkerPayload,
    ApplicationRunRequest,
    JobLeadWorkerPayload,
    WorkerRunRequest,
)
from apps.api.app.services.saved_searches import apply_feedback_for_job
from apps.api.app.services.storage import get_latest_profile, get_profile_payload


def build_worker_request(
    session: Session,
    *,
    draft: ApplicationDraft,
    payload: ApplicationRunRequest,
) -> tuple[WorkerRunRequest, JobLead]:
    profile = get_latest_profile(session)
    profile_payload = get_profile_payload(profile)
    if profile is None or profile_payload is None:
        raise ValueError("Profile data is required before running the worker.")

    job = draft.job_lead
    if job is None:
        raise ValueError("Application draft is missing a linked job lead.")

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
        platform=job.source if job.source in {"greenhouse", "lever", "ashbyhq"} else "generic",
        profile=profile_payload,
        job=job_payload,
        draft=draft_payload,
        answer_overrides=payload.answer_overrides,
        dry_run=payload.dry_run,
        confirm_submit=payload.confirm_submit,
        fixture_html=payload.fixture_html,
    )
    return worker_request, job


def create_worker_run_placeholder(
    session: Session,
    *,
    draft: ApplicationDraft,
    worker_request: WorkerRunRequest,
    status: str = "queued",
) -> WorkerRun:
    worker_run = WorkerRun(
        application_draft_id=draft.id,
        platform=worker_request.platform,
        target_url=str(worker_request.target_url),
        dry_run=worker_request.dry_run,
        status=status,
        actions=[],
        logs=[],
        fields=[],
        review_items=[],
        preview_summary={},
        profile_snapshot=worker_request.profile.model_dump(mode="json"),
        job_snapshot=worker_request.job.model_dump(mode="json"),
        draft_snapshot=worker_request.draft.model_dump(mode="json"),
        screenshot_path=None,
    )
    session.add(worker_run)
    session.flush()
    return worker_run


def persist_worker_result(
    session: Session,
    *,
    worker_run: WorkerRun,
    draft: ApplicationDraft,
    job: JobLead,
    result: dict,
) -> WorkerRun:
    worker_run.platform = result["platform"]
    worker_run.target_url = result["target_url"]
    worker_run.dry_run = result["dry_run"]
    worker_run.status = result["status"]
    worker_run.actions = result["actions"]
    worker_run.logs = result["logs"]
    worker_run.fields = result["fields"]
    worker_run.review_items = result["review_items"]
    worker_run.preview_summary = result["preview_summary"]
    worker_run.profile_snapshot = result["profile_snapshot"]
    worker_run.job_snapshot = result["job_snapshot"]
    worker_run.draft_snapshot = result["draft_snapshot"]
    worker_run.screenshot_path = result["screenshot_path"]

    draft.status = result["status"]
    if result["status"] in {"submitted", "submit_clicked"}:
        job.status = result["status"]
        if result["status"] == "submitted":
            job.crm_stage = "applied"
            job.last_contacted_at = datetime.now(UTC)
            apply_feedback_for_job(session, job_id=job.id, signal="applied")
    return worker_run
