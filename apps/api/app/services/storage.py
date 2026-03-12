from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.config import settings
from apps.api.app.models import ApplicationDraft, CandidateProfile, JobLead, ProfileSource, WorkerRun
from apps.api.app.schemas import (
    CandidateProfilePayload,
    ProfileSourcePayload,
    ProfileUpdateRequest,
    SearchPreferencesPayload,
)
from apps.api.app.services.matching import rank_job
from apps.api.app.services.profile_sources.linkedin_profile import merge_profile_payloads
from apps.api.app.services.saved_searches import (
    list_saved_searches,
    rerank_saved_search_matches,
    sync_default_saved_search,
)
from apps.api.app.services.search_preferences import normalize_search_preferences, seed_search_preferences


def get_latest_profile(session: Session) -> CandidateProfile | None:
    return session.execute(
        select(CandidateProfile).order_by(CandidateProfile.id.desc()).limit(1)
    ).scalar_one_or_none()


def get_profile_payload(profile: CandidateProfile | None) -> CandidateProfilePayload | None:
    if profile is None or not profile.merged_profile:
        return None
    payload = CandidateProfilePayload.model_validate(profile.merged_profile)
    return payload if _profile_has_content(payload) else None


def get_search_preferences(profile: CandidateProfile | None) -> SearchPreferencesPayload:
    if profile is None:
        return seed_search_preferences(None)
    if profile.search_preferences:
        return normalize_search_preferences(profile.search_preferences)
    return seed_search_preferences(get_profile_payload(profile))


def save_profile_source(
    session: Session,
    *,
    source_type: str,
    source_label: str,
    raw_text: str,
    payload: CandidateProfilePayload,
    confidence: dict[str, float],
) -> CandidateProfile:
    profile = get_latest_profile(session)
    existing_payload = get_profile_payload(profile)
    cv_payload = payload if source_type == "cv" else existing_payload
    linkedin_payload = payload if source_type == "linkedin" else existing_payload
    merged_payload, field_sources = merge_profile_payloads(cv_payload, linkedin_payload)

    if profile is None:
        profile = CandidateProfile(source_of_truth="cv")
        session.add(profile)
        session.flush()

    profile.full_name = merged_payload.full_name
    profile.headline = merged_payload.headline
    profile.email = merged_payload.email
    profile.phone = merged_payload.phone
    profile.location = merged_payload.location
    profile.raw_cv_text = raw_text if source_type == "cv" else profile.raw_cv_text
    profile.merged_profile = merged_payload.model_dump(mode="json")
    profile.field_sources = field_sources
    if profile.search_preferences_customized and profile.search_preferences:
        search_preferences = normalize_search_preferences(profile.search_preferences)
    else:
        search_preferences = seed_search_preferences(merged_payload)
        profile.search_preferences_customized = False
    profile.search_preferences = search_preferences.model_dump(mode="json")
    sync_default_saved_search(session, profile, search_preferences)
    rerank_all_jobs(session, merged_payload, search_preferences)

    source = ProfileSource(
        profile_id=profile.id,
        source_type=source_type,
        source_label=source_label,
        raw_text=raw_text,
        parsed_payload=payload.model_dump(mode="json"),
        confidence=confidence,
    )
    session.add(source)
    session.commit()
    session.refresh(profile)
    return profile


def update_profile_manually(session: Session, payload: ProfileUpdateRequest) -> CandidateProfile:
    profile = get_latest_profile(session)
    if profile is None:
        profile = CandidateProfile(source_of_truth="manual")
        session.add(profile)
        session.flush()

    profile.full_name = payload.full_name
    profile.headline = payload.headline
    profile.email = payload.email
    profile.phone = payload.phone
    profile.location = payload.location
    profile.source_of_truth = "manual"
    merged_profile = payload.model_dump(mode="json", exclude={"search_preferences"})
    profile.merged_profile = merged_profile
    profile.field_sources = {field: "manual" for field in merged_profile.keys()}
    if payload.search_preferences is not None:
        search_preferences = normalize_search_preferences(payload.search_preferences)
        profile.search_preferences_customized = True
    elif profile.search_preferences_customized and profile.search_preferences:
        search_preferences = normalize_search_preferences(profile.search_preferences)
    else:
        search_preferences = seed_search_preferences(payload)
        profile.search_preferences_customized = False
    profile.search_preferences = search_preferences.model_dump(mode="json")
    sync_default_saved_search(session, profile, search_preferences)
    rerank_all_jobs(session, payload, search_preferences)
    session.commit()
    session.refresh(profile)
    return profile


def update_search_preferences(
    session: Session, payload: SearchPreferencesPayload
) -> CandidateProfile:
    profile = get_latest_profile(session)
    if profile is None:
        profile = CandidateProfile(
            source_of_truth="manual",
            merged_profile=CandidateProfilePayload().model_dump(mode="json"),
            field_sources={},
        )
        session.add(profile)
        session.flush()
    profile.search_preferences = normalize_search_preferences(payload).model_dump(mode="json")
    profile.search_preferences_customized = True
    search_preferences = get_search_preferences(profile)
    sync_default_saved_search(session, profile, search_preferences)
    profile_payload = get_profile_payload(profile)
    if profile_payload is not None:
        rerank_all_jobs(session, profile_payload, search_preferences)
    session.commit()
    session.refresh(profile)
    return profile


def list_profile_sources(session: Session) -> list[ProfileSourcePayload]:
    profile = get_latest_profile(session)
    if profile is None:
        return []
    rows = session.execute(
        select(ProfileSource)
        .where(ProfileSource.profile_id == profile.id)
        .order_by(ProfileSource.id.desc())
    ).scalars()
    return [
        ProfileSourcePayload(
            id=row.id,
            source_type=row.source_type,
            source_label=row.source_label,
            confidence=row.confidence,
            payload=CandidateProfilePayload.model_validate(row.parsed_payload),
        )
        for row in rows
    ]


def delete_profile_source(session: Session, source_id: int) -> dict[str, int] | None:
    source = session.execute(select(ProfileSource).where(ProfileSource.id == source_id)).scalar_one_or_none()
    if source is None:
        return None

    profile = source.profile
    if profile is None:
        session.delete(source)
        session.commit()
        return {"remaining_sources": 0}

    latest_cv_source = _latest_profile_source(session, profile.id, "cv")
    removed_current_resume = (
        source.source_type == "cv"
        and latest_cv_source is not None
        and latest_cv_source.id == source.id
    )

    session.delete(source)
    session.flush()
    if removed_current_resume:
        _delete_resume_artifacts()

    _rebuild_profile_after_source_delete(
        session,
        profile,
        removed_source_type=source.source_type,
        removed_current_resume=removed_current_resume,
    )
    remaining_sources = session.execute(
        select(ProfileSource).where(ProfileSource.profile_id == profile.id)
    ).scalars().all()
    session.commit()
    return {"remaining_sources": len(remaining_sources)}


def upsert_job_lead(session: Session, payload: dict) -> JobLead:
    now = datetime.now(UTC)
    existing = session.execute(
        select(JobLead).where(
            JobLead.source == payload["source"], JobLead.external_id == str(payload["external_id"])
        )
    ).scalar_one_or_none()
    if existing is None and payload.get("url"):
        existing = session.execute(
            select(JobLead).where(JobLead.source == payload["source"], JobLead.url == payload["url"])
        ).scalar_one_or_none()
    if existing:
        for field_name, value in payload.items():
            if field_name in {
                "crm_stage",
                "crm_notes",
                "follow_up_at",
                "last_contacted_at",
                "first_seen_at",
                "last_seen_at",
                "last_checked_at",
                "closed_at",
                "is_active",
            }:
                continue
            if (
                field_name == "status"
                and value == "discovered"
                and existing.status in {"submitted", "submit_clicked"}
            ):
                continue
            setattr(existing, field_name, value)
        existing.last_seen_at = now
        existing.last_checked_at = now
        existing.is_active = True
        if existing.closed_at is not None:
            existing.closed_at = None
        session.commit()
        session.refresh(existing)
        return existing

    job = JobLead(
        **payload,
        first_seen_at=now,
        last_seen_at=now,
        last_checked_at=now,
        is_active=True,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def list_jobs(session: Session) -> list[JobLead]:
    return list(
        session.execute(
            select(JobLead).order_by(
                JobLead.score.desc().nullslast(),
                JobLead.last_seen_at.desc().nullslast(),
                JobLead.id.desc(),
            )
        ).scalars()
    )


def list_applications(session: Session) -> list[ApplicationDraft]:
    return list(
        session.execute(select(ApplicationDraft).order_by(ApplicationDraft.id.desc())).scalars()
    )


def list_worker_runs(session: Session, limit: int = 10) -> list[WorkerRun]:
    return list(
        session.execute(
            select(WorkerRun).order_by(WorkerRun.created_at.desc(), WorkerRun.id.desc()).limit(limit)
        ).scalars()
    )


def delete_job_lead(session: Session, job_id: int) -> dict[str, int] | None:
    job = session.execute(select(JobLead).where(JobLead.id == job_id)).scalar_one_or_none()
    if job is None:
        return None

    deleted_counts = _delete_job_lead_records(session, job)
    session.commit()
    return deleted_counts


def delete_job_leads(session: Session, job_ids: list[int]) -> tuple[list[int], dict[str, int]]:
    normalized_ids = list(dict.fromkeys(job_id for job_id in job_ids if job_id > 0))
    if not normalized_ids:
        return [], {"job_leads": 0, "application_drafts": 0, "worker_runs": 0}

    jobs = session.execute(
        select(JobLead).where(JobLead.id.in_(normalized_ids)).order_by(JobLead.id)
    ).scalars().all()
    deleted_ids: list[int] = []
    deleted_counts = {"job_leads": 0, "application_drafts": 0, "worker_runs": 0}
    for job in jobs:
        counts = _delete_job_lead_records(session, job)
        deleted_ids.append(job.id)
        deleted_counts["job_leads"] += 1
        deleted_counts["application_drafts"] += counts["application_drafts"]
        deleted_counts["worker_runs"] += counts["worker_runs"]

    session.commit()
    return deleted_ids, deleted_counts


def delete_application_draft(session: Session, application_id: int) -> dict[str, int] | None:
    draft = session.execute(
        select(ApplicationDraft).where(ApplicationDraft.id == application_id)
    ).scalar_one_or_none()
    if draft is None:
        return None

    deleted_counts = {"worker_runs": _delete_application_draft_records(session, draft)}
    session.commit()
    return deleted_counts


def delete_worker_run(session: Session, run_id: int) -> dict[str, int] | None:
    worker_run = session.execute(
        select(WorkerRun).where(WorkerRun.id == run_id)
    ).scalar_one_or_none()
    if worker_run is None:
        return None

    session.delete(worker_run)
    session.commit()
    return {}


def rerank_all_jobs(
    session: Session,
    profile_payload: CandidateProfilePayload,
    search_preferences: SearchPreferencesPayload | None = None,
) -> None:
    ranking_preferences = search_preferences or seed_search_preferences(profile_payload)
    jobs = session.execute(select(JobLead)).scalars().all()
    for job in jobs:
        ranking = rank_job(profile_payload, _job_to_payload(job), ranking_preferences)
        job.score = ranking.score
        job.score_details = ranking.model_dump(mode="json")
    profile = get_latest_profile(session)
    if profile is not None:
        rerank_saved_search_matches(
            session,
            profile_payload=profile_payload,
            saved_searches=list_saved_searches(session, profile.id),
        )


def _delete_application_draft_records(session: Session, draft: ApplicationDraft) -> int:
    worker_runs = session.execute(
        select(WorkerRun).where(WorkerRun.application_draft_id == draft.id)
    ).scalars().all()
    for worker_run in worker_runs:
        session.delete(worker_run)

    session.delete(draft)
    return len(worker_runs)


def _delete_job_lead_records(session: Session, job: JobLead) -> dict[str, int]:
    drafts = session.execute(
        select(ApplicationDraft).where(ApplicationDraft.job_lead_id == job.id)
    ).scalars().all()
    deleted_counts = {
        "application_drafts": len(drafts),
        "worker_runs": 0,
    }
    for draft in drafts:
        deleted_counts["worker_runs"] += _delete_application_draft_records(session, draft)

    session.delete(job)
    return deleted_counts


def _rebuild_profile_after_source_delete(
    session: Session,
    profile: CandidateProfile,
    *,
    removed_source_type: str,
    removed_current_resume: bool,
) -> None:
    latest_cv_source = _latest_profile_source(session, profile.id, "cv")
    latest_linkedin_source = _latest_profile_source(session, profile.id, "linkedin")

    if profile.source_of_truth == "manual":
        merged_profile = CandidateProfilePayload.model_validate(
            profile.merged_profile or CandidateProfilePayload().model_dump(mode="json")
        )
        if removed_source_type == "cv" and removed_current_resume:
            merged_links = dict(merged_profile.links)
            merged_links.pop("resume_path", None)
            merged_profile = merged_profile.model_copy(update={"links": merged_links})
            profile.merged_profile = merged_profile.model_dump(mode="json")
        profile.raw_cv_text = latest_cv_source.raw_text if latest_cv_source else None
        if profile.search_preferences_customized and profile.search_preferences:
            search_preferences = normalize_search_preferences(profile.search_preferences)
        else:
            search_preferences = seed_search_preferences(merged_profile)
            profile.search_preferences_customized = False
        profile.search_preferences = search_preferences.model_dump(mode="json")
        sync_default_saved_search(session, profile, search_preferences)
        rerank_all_jobs(session, merged_profile, search_preferences)
        return

    cv_payload = _payload_from_source(latest_cv_source)
    linkedin_payload = _payload_from_source(latest_linkedin_source)
    merged_payload, field_sources = merge_profile_payloads(cv_payload, linkedin_payload)

    profile.full_name = merged_payload.full_name
    profile.headline = merged_payload.headline
    profile.email = merged_payload.email
    profile.phone = merged_payload.phone
    profile.location = merged_payload.location
    profile.raw_cv_text = latest_cv_source.raw_text if latest_cv_source else None
    profile.source_of_truth = "cv" if latest_cv_source else "linkedin" if latest_linkedin_source else "manual"
    profile.merged_profile = merged_payload.model_dump(mode="json")
    profile.field_sources = field_sources
    if profile.search_preferences_customized and profile.search_preferences:
        search_preferences = normalize_search_preferences(profile.search_preferences)
    else:
        search_preferences = seed_search_preferences(merged_payload)
        profile.search_preferences_customized = False
    profile.search_preferences = search_preferences.model_dump(mode="json")
    sync_default_saved_search(session, profile, search_preferences)
    rerank_all_jobs(session, merged_payload, search_preferences)


def _latest_profile_source(
    session: Session,
    profile_id: int,
    source_type: str,
) -> ProfileSource | None:
    return session.execute(
        select(ProfileSource)
        .where(ProfileSource.profile_id == profile_id, ProfileSource.source_type == source_type)
        .order_by(ProfileSource.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _payload_from_source(source: ProfileSource | None) -> CandidateProfilePayload | None:
    if source is None:
        return None
    return CandidateProfilePayload.model_validate(source.parsed_payload)


def _delete_resume_artifacts() -> None:
    upload_dir = settings.data_dir / "uploads"
    if not upload_dir.exists():
        return
    for path in upload_dir.glob("latest_resume.*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def _profile_has_content(payload: CandidateProfilePayload) -> bool:
    data = payload.model_dump(mode="json")
    for value in data.values():
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, dict)) and value:
            return True
        if value is not None and not isinstance(value, (str, list, dict)):
            return True
    return False


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
