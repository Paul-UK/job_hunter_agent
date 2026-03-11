from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import settings
from apps.api.app.db import get_session
from apps.api.app.models import ApplicationDraft, WorkerRun
from apps.api.app.schemas import (
    ApplicationDraftAssistRequest,
    ApplicationDraftAssistResponse,
    ApplicationDraftResponse,
    ApplicationDraftWorkerPayload,
    ApplicationRunRequest,
    DeleteResponse,
    JobLeadWorkerPayload,
    WorkerRunRequest,
    WorkerRunResponse,
)
from apps.api.app.services.ai_drafting import suggest_application_text
from apps.api.app.services.llm import get_llm_client
from apps.api.app.services.matching import rank_job
from apps.api.app.services.storage import (
    delete_application_draft,
    delete_worker_run,
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


@router.delete("/runs/{run_id}", response_model=DeleteResponse)
def remove_worker_run(run_id: int, session: Session = Depends(get_session)) -> DeleteResponse:
    deleted_counts = delete_worker_run(session, run_id)
    if deleted_counts is None:
        raise HTTPException(status_code=404, detail="Worker run not found.")
    return DeleteResponse(
        entity="worker_run",
        deleted_id=run_id,
        deleted_counts=deleted_counts,
    )


@router.get("/runs/{run_id}/screenshot")
def read_worker_run_screenshot(run_id: int, session: Session = Depends(get_session)) -> FileResponse:
    worker_run = session.execute(select(WorkerRun).where(WorkerRun.id == run_id)).scalar_one_or_none()
    if worker_run is None:
        raise HTTPException(status_code=404, detail="Worker run not found.")

    screenshot_path = _resolve_screenshot_path(worker_run.screenshot_path)
    if screenshot_path is None:
        raise HTTPException(status_code=404, detail="Worker run screenshot not found.")

    return FileResponse(path=screenshot_path, filename=screenshot_path.name)


@router.post("/{application_id}/assist", response_model=ApplicationDraftAssistResponse)
def assist_application_text(
    application_id: int,
    payload: ApplicationDraftAssistRequest,
    session: Session = Depends(get_session),
) -> ApplicationDraftAssistResponse:
    draft = session.execute(
        select(ApplicationDraft).where(ApplicationDraft.id == application_id)
    ).scalar_one_or_none()
    if draft is None:
        raise HTTPException(status_code=404, detail="Application draft not found.")

    profile = get_latest_profile(session)
    profile_payload = get_profile_payload(profile)
    if profile is None or profile_payload is None:
        raise HTTPException(
            status_code=400,
            detail="Profile data is required before generating AI draft text.",
        )

    job = draft.job_lead
    if job is None:
        raise HTTPException(
            status_code=400,
            detail="Application draft is missing a linked job lead.",
        )

    if payload.target == "question_answer" and not (payload.question or "").strip():
        raise HTTPException(status_code=400, detail="Question text is required for question answers.")

    llm_client = get_llm_client()
    job_payload = _job_to_payload(job)
    ranking = rank_job(profile_payload, job_payload)
    suggestion = suggest_application_text(
        target=payload.target,
        profile=profile_payload,
        job=job_payload,
        ranking=ranking,
        research=job.research or {},
        llm_client=llm_client,
        question=(payload.question or "").strip() or None,
        current_text=payload.current_text,
        supporting_answers=[
            {
                "question": str(answer.get("question") or ""),
                "answer": str(answer.get("answer") or ""),
            }
            for answer in (draft.screening_answers or [])
        ],
    )

    updated_draft: ApplicationDraft | None = None
    if payload.persist:
        if payload.target == "cover_note":
            draft.cover_note = suggestion.answer
        else:
            draft.screening_answers = _upsert_screening_answer(
                draft.screening_answers or [],
                question=(payload.question or "").strip(),
                answer=suggestion.answer,
            )
        session.commit()
        session.refresh(draft)
        updated_draft = draft

    return ApplicationDraftAssistResponse(
        text=suggestion.answer,
        confidence=suggestion.confidence,
        reasoning=suggestion.reasoning,
        updated_draft=updated_draft,
    )


@router.delete("/{application_id}", response_model=DeleteResponse)
def remove_application(
    application_id: int,
    session: Session = Depends(get_session),
) -> DeleteResponse:
    deleted_counts = delete_application_draft(session, application_id)
    if deleted_counts is None:
        raise HTTPException(status_code=404, detail="Application draft not found.")
    return DeleteResponse(
        entity="application_draft",
        deleted_id=application_id,
        deleted_counts=deleted_counts,
    )


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
        platform=job.source if job.source in {"greenhouse", "lever", "ashbyhq"} else "generic",
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
    if result["status"] in {"submitted", "submit_clicked"}:
        job.status = result["status"]
    session.add(worker_run)
    session.commit()
    session.refresh(worker_run)
    return worker_run


def _job_to_payload(job) -> dict:
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


def _resolve_screenshot_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None

    candidate = Path(raw_path).expanduser().resolve()
    artifacts_root = settings.artifacts_dir.resolve()
    if not candidate.is_file():
        return None
    if not candidate.is_relative_to(artifacts_root):
        return None
    return candidate


def _upsert_screening_answer(
    current_answers: list[dict],
    *,
    question: str,
    answer: str,
) -> list[dict[str, str]]:
    normalized_question = question.strip()
    next_answers: list[dict[str, str]] = []
    updated = False
    for current_answer in current_answers:
        current_question = str(current_answer.get("question") or "").strip()
        current_value = str(current_answer.get("answer") or "").strip()
        if current_question == normalized_question:
            next_answers.append({"question": current_question, "answer": answer})
            updated = True
            continue
        next_answers.append({"question": current_question, "answer": current_value})

    if not updated and normalized_question:
        next_answers.append({"question": normalized_question, "answer": answer})
    return next_answers
