from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    headline: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(255))
    source_of_truth: Mapped[str] = mapped_column(String(32), default="cv")
    raw_cv_text: Mapped[str | None] = mapped_column(Text)
    merged_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    field_sources: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sources: Mapped[list[ProfileSource]] = relationship(back_populates="profile")
    applications: Mapped[list[ApplicationDraft]] = relationship(back_populates="profile")


class ProfileSource(Base):
    __tablename__ = "profile_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id"))
    source_type: Mapped[str] = mapped_column(String(32))
    source_label: Mapped[str] = mapped_column(String(255))
    raw_text: Mapped[str] = mapped_column(Text)
    parsed_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped[CandidateProfile] = relationship(back_populates="sources")


class JobLead(Base):
    __tablename__ = "job_leads"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    employment_type: Mapped[str | None] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str] = mapped_column(Text)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float | None] = mapped_column(Float)
    score_details: Mapped[dict] = mapped_column(JSON, default=dict)
    research: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="discovered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    applications: Mapped[list[ApplicationDraft]] = relationship(back_populates="job_lead")


class ApplicationDraft(Base):
    __tablename__ = "application_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id"))
    job_lead_id: Mapped[int] = mapped_column(ForeignKey("job_leads.id"))
    tailored_summary: Mapped[str] = mapped_column(Text)
    cover_note: Mapped[str] = mapped_column(Text)
    resume_bullets: Mapped[list] = mapped_column(JSON, default=list)
    screening_answers: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="drafted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="applications")
    job_lead: Mapped[JobLead] = relationship(back_populates="applications")
    worker_runs: Mapped[list[WorkerRun]] = relationship(back_populates="application_draft")


class WorkerRun(Base):
    __tablename__ = "worker_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_draft_id: Mapped[int | None] = mapped_column(ForeignKey("application_drafts.id"))
    platform: Mapped[str] = mapped_column(String(32))
    target_url: Mapped[str] = mapped_column(String(1024))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="planned")
    actions: Mapped[list] = mapped_column(JSON, default=list)
    logs: Mapped[list] = mapped_column(JSON, default=list)
    fields: Mapped[list] = mapped_column(JSON, default=list)
    review_items: Mapped[list] = mapped_column(JSON, default=list)
    preview_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    job_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    draft_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    screenshot_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    application_draft: Mapped[ApplicationDraft | None] = relationship(back_populates="worker_runs")
