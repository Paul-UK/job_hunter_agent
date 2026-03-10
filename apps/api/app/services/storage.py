from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import ApplicationDraft, CandidateProfile, JobLead, ProfileSource, WorkerRun
from apps.api.app.schemas import CandidateProfilePayload, ProfileSourcePayload
from apps.api.app.services.matching import rank_job
from apps.api.app.services.profile_sources.linkedin_profile import merge_profile_payloads


def get_latest_profile(session: Session) -> CandidateProfile | None:
    return session.execute(
        select(CandidateProfile).order_by(CandidateProfile.id.desc())
    ).scalar_one_or_none()


def get_profile_payload(profile: CandidateProfile | None) -> CandidateProfilePayload | None:
    if profile is None or not profile.merged_profile:
        return None
    return CandidateProfilePayload.model_validate(profile.merged_profile)


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
    rerank_all_jobs(session, merged_payload)

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


def update_profile_manually(session: Session, payload: CandidateProfilePayload) -> CandidateProfile:
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
    profile.merged_profile = payload.model_dump(mode="json")
    profile.field_sources = {field: "manual" for field in payload.model_dump(mode="json").keys()}
    rerank_all_jobs(session, payload)
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
            source_type=row.source_type,
            source_label=row.source_label,
            confidence=row.confidence,
            payload=CandidateProfilePayload.model_validate(row.parsed_payload),
        )
        for row in rows
    ]


def upsert_job_lead(session: Session, payload: dict) -> JobLead:
    existing = session.execute(
        select(JobLead).where(
            JobLead.source == payload["source"], JobLead.external_id == str(payload["external_id"])
        )
    ).scalar_one_or_none()
    if existing:
        for field_name, value in payload.items():
            setattr(existing, field_name, value)
        session.commit()
        session.refresh(existing)
        return existing

    job = JobLead(**payload)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def list_jobs(session: Session) -> list[JobLead]:
    return list(
        session.execute(
            select(JobLead).order_by(JobLead.score.desc().nullslast(), JobLead.id.desc())
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


def rerank_all_jobs(session: Session, profile_payload: CandidateProfilePayload) -> None:
    jobs = session.execute(select(JobLead)).scalars().all()
    for job in jobs:
        ranking = rank_job(profile_payload, _job_to_payload(job))
        job.score = ranking.score
        job.score_details = ranking.model_dump(mode="json")


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
