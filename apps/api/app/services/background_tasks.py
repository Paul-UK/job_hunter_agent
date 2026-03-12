from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import settings
from apps.api.app.db import SessionLocal
from apps.api.app.models import (
    ApplicationDraft,
    BackgroundTask,
    CandidateProfile,
    DiscoveryRun,
    SavedSearch,
    WorkerRun,
)
from apps.api.app.schemas import ApplicationRunRequest, CandidateProfilePayload
from apps.api.app.services.job_discovery import WebDiscoveryError, discover_jobs_from_web
from apps.api.app.services.saved_searches import (
    mark_saved_search_run_finished,
    mark_saved_search_run_started,
    upsert_saved_search_match,
)
from apps.api.app.services.search_preferences import normalize_search_preferences
from apps.api.app.services.storage import get_profile_payload, upsert_job_lead
from apps.api.app.services.worker_runs import (
    build_worker_request,
    create_worker_run_placeholder,
    persist_worker_result,
)
from apps.worker.main import run_worker


def list_background_tasks(session: Session, limit: int = 25) -> list[BackgroundTask]:
    return list(
        session.execute(
            select(BackgroundTask)
            .order_by(BackgroundTask.created_at.desc(), BackgroundTask.id.desc())
            .limit(limit)
        ).scalars()
    )


def enqueue_discovery_task(
    session: Session,
    *,
    saved_search: SavedSearch,
    profile: CandidateProfile,
    trigger_kind: str = "manual",
) -> tuple[BackgroundTask, DiscoveryRun]:
    discovery_run = DiscoveryRun(
        saved_search_id=saved_search.id,
        profile_id=profile.id,
        trigger_kind=trigger_kind,
        status="queued",
        model_name=settings.gemini_discovery_model,
        search_preferences_snapshot=saved_search.search_preferences or {},
        diagnostics={},
    )
    session.add(discovery_run)
    session.flush()

    task = BackgroundTask(
        task_type="discovery_run",
        title=f"Run saved search: {saved_search.name}",
        status="queued",
        profile_id=profile.id,
        saved_search_id=saved_search.id,
        discovery_run_id=discovery_run.id,
        payload_json={"trigger_kind": trigger_kind},
        max_attempts=settings.background_task_max_attempts,
    )
    session.add(task)
    saved_search.last_status = "queued"
    if saved_search.next_run_at is None:
        saved_search.next_run_at = datetime.now(UTC)
    session.flush()
    return task, discovery_run


def enqueue_worker_task(
    session: Session,
    *,
    draft: ApplicationDraft,
    payload: ApplicationRunRequest,
) -> tuple[BackgroundTask, WorkerRun]:
    existing_task = session.execute(
        select(BackgroundTask)
        .where(
            BackgroundTask.application_draft_id == draft.id,
            BackgroundTask.task_type == "worker_run",
            BackgroundTask.status.in_(("queued", "running")),
        )
        .order_by(BackgroundTask.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if existing_task is not None:
        existing_worker_run = _require_related(
            session,
            WorkerRun,
            existing_task.worker_run_id,
            "worker run",
        )
        return existing_task, existing_worker_run

    worker_request, _job = build_worker_request(session, draft=draft, payload=payload)
    worker_run = create_worker_run_placeholder(
        session,
        draft=draft,
        worker_request=worker_request,
        status="queued",
    )
    draft.status = "queued"
    task = BackgroundTask(
        task_type="worker_run",
        title=f"Run worker for application {draft.id}",
        status="queued",
        application_draft_id=draft.id,
        worker_run_id=worker_run.id,
        payload_json=payload.model_dump(mode="json"),
        max_attempts=1,
    )
    session.add(task)
    session.flush()
    return task, worker_run


def enqueue_due_saved_search_runs(session: Session) -> list[BackgroundTask]:
    now = datetime.now(UTC)
    queued_tasks: list[BackgroundTask] = []
    saved_searches = session.execute(
        select(SavedSearch)
        .where(
            SavedSearch.enabled.is_(True),
            SavedSearch.next_run_at.is_not(None),
            SavedSearch.next_run_at <= now,
        )
        .order_by(SavedSearch.next_run_at.asc(), SavedSearch.id.asc())
    ).scalars().all()
    for saved_search in saved_searches:
        existing_task = session.execute(
            select(BackgroundTask).where(
                BackgroundTask.saved_search_id == saved_search.id,
                BackgroundTask.task_type == "discovery_run",
                BackgroundTask.status.in_(("queued", "running")),
            ).limit(1)
        ).scalar_one_or_none()
        if existing_task is not None:
            continue
        if saved_search.profile is None:
            continue
        task, _run = enqueue_discovery_task(
            session,
            saved_search=saved_search,
            profile=saved_search.profile,
            trigger_kind="scheduled",
        )
        queued_tasks.append(task)
    return queued_tasks


def process_pending_background_tasks(limit: int = 1, *, include_scheduled: bool = True) -> int:
    processed = 0
    if include_scheduled:
        with SessionLocal() as session:
            enqueue_due_saved_search_runs(session)
            session.commit()

    while processed < limit:
        with SessionLocal() as session:
            task = session.execute(
                select(BackgroundTask)
                .where(BackgroundTask.status == "queued")
                .order_by(BackgroundTask.scheduled_at.asc(), BackgroundTask.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if task is None:
                break
            _mark_task_running(task)
            session.commit()
            task_id = task.id

        with SessionLocal() as session:
            task = session.execute(select(BackgroundTask).where(BackgroundTask.id == task_id)).scalar_one()
            try:
                if task.task_type == "discovery_run":
                    _execute_discovery_task(session, task)
                elif task.task_type == "worker_run":
                    _execute_worker_task(session, task)
                else:
                    raise RuntimeError(f"Unsupported background task type '{task.task_type}'.")
            except Exception as exc:
                _handle_task_failure(session, task, exc)
            else:
                task.status = "succeeded"
                task.error_message = None
                task.completed_at = datetime.now(UTC)
                task.heartbeat_at = task.completed_at
                session.commit()
                processed += 1
                continue
            session.commit()
            processed += 1
    return processed


def _execute_discovery_task(session: Session, task: BackgroundTask) -> None:
    discovery_run = _require_related(session, DiscoveryRun, task.discovery_run_id, "discovery run")
    saved_search = _require_related(session, SavedSearch, task.saved_search_id, "saved search")
    profile = _require_related(session, CandidateProfile, task.profile_id, "profile")
    profile_payload = get_profile_payload(profile)
    if profile_payload is None:
        raise RuntimeError("Profile data is required before running saved-search discovery.")

    discovery_run.status = "running"
    discovery_run.started_at = discovery_run.started_at or datetime.now(UTC)
    discovery_run.error_message = None
    mark_saved_search_run_started(saved_search)
    session.commit()

    try:
        result = discover_jobs_from_web(
            profile=profile_payload,
            search_preferences=normalize_search_preferences(discovery_run.search_preferences_snapshot),
        )
    except WebDiscoveryError:
        raise

    discovered_ids: list[int] = []
    for job_payload in result.jobs:
        job = upsert_job_lead(session, job_payload)
        match = upsert_saved_search_match(
            session,
            saved_search=saved_search,
            job=job,
            profile_payload=profile_payload,
            discovery_run=discovery_run,
        )
        discovered_ids.append(job.id)
        task.result_json = {
            "job_ids": discovered_ids,
            "saved_search_match_ids": [
                *task.result_json.get("saved_search_match_ids", []),
                match.id,
            ],
        }

    discovery_run.status = "completed"
    discovery_run.completed_at = datetime.now(UTC)
    discovery_run.search_queries = result.search_queries
    discovery_run.source_urls = result.source_urls
    discovery_run.grounded_pages_count = result.grounded_pages_count
    discovery_run.jobs_created_count = len(discovered_ids)
    diagnostics = dict(getattr(result, "diagnostics", {}) or {})
    diagnostics.setdefault("job_ids", discovered_ids)
    discovery_run.diagnostics = diagnostics
    mark_saved_search_run_finished(saved_search, status="completed")
    task.result_json = {
        **(task.result_json or {}),
        "discovery_run_id": discovery_run.id,
        "job_ids": discovered_ids,
        "jobs_created_count": len(discovered_ids),
    }
    session.commit()


def _execute_worker_task(session: Session, task: BackgroundTask) -> None:
    worker_run = _require_related(session, WorkerRun, task.worker_run_id, "worker run")
    draft = _require_related(session, ApplicationDraft, task.application_draft_id, "application draft")
    payload = ApplicationRunRequest.model_validate(task.payload_json or {})
    worker_request, job = build_worker_request(session, draft=draft, payload=payload)
    worker_run.status = "running"
    worker_run.logs = [*worker_run.logs, "Background worker task started."]
    session.commit()

    result = run_worker(worker_request)
    persist_worker_result(session, worker_run=worker_run, draft=draft, job=job, result=result)
    task.result_json = {
        "worker_run_id": worker_run.id,
        "worker_status": worker_run.status,
        "application_draft_id": draft.id,
    }
    session.commit()


def _handle_task_failure(session: Session, task: BackgroundTask, exc: Exception) -> None:
    now = datetime.now(UTC)
    error_message = str(exc).strip() or type(exc).__name__
    task.error_message = error_message
    task.heartbeat_at = now

    if task.task_type == "discovery_run" and task.discovery_run_id is not None:
        discovery_run = session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == task.discovery_run_id)
        ).scalar_one_or_none()
        if discovery_run is not None:
            discovery_run.error_message = error_message
            if task.attempt_count < task.max_attempts:
                discovery_run.status = "retrying"
            else:
                discovery_run.status = "failed"
                discovery_run.completed_at = now
        saved_search = (
            session.execute(select(SavedSearch).where(SavedSearch.id == task.saved_search_id)).scalar_one_or_none()
            if task.saved_search_id is not None
            else None
        )
        if saved_search is not None:
            if task.attempt_count < task.max_attempts:
                saved_search.last_status = "retrying"
                saved_search.last_error = error_message
            else:
                mark_saved_search_run_finished(saved_search, status="failed", error_message=error_message)

    if task.task_type == "worker_run" and task.worker_run_id is not None:
        worker_run = session.execute(
            select(WorkerRun).where(WorkerRun.id == task.worker_run_id)
        ).scalar_one_or_none()
        if worker_run is not None:
            worker_run.status = "failed"
            worker_run.logs = [*worker_run.logs, f"Background task failed: {error_message}"]

    if task.attempt_count < task.max_attempts:
        task.status = "queued"
        task.scheduled_at = now + timedelta(seconds=30)
    else:
        task.status = "failed"
        task.completed_at = now


def _mark_task_running(task: BackgroundTask) -> None:
    now = datetime.now(UTC)
    task.status = "running"
    task.started_at = task.started_at or now
    task.heartbeat_at = now
    task.attempt_count += 1
    task.error_message = None


def _require_related(session: Session, model, entity_id: int | None, label: str):
    if entity_id is None:
        raise RuntimeError(f"Background task is missing a {label} reference.")
    entity = session.execute(select(model).where(model.id == entity_id)).scalar_one_or_none()
    if entity is None:
        raise RuntimeError(f"Background task {label} was not found.")
    return entity
