from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    search_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    search_preferences_customized: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sources: Mapped[list[ProfileSource]] = relationship(back_populates="profile")
    applications: Mapped[list[ApplicationDraft]] = relationship(back_populates="profile")
    saved_searches: Mapped[list[SavedSearch]] = relationship(back_populates="profile")
    discovery_runs: Mapped[list[DiscoveryRun]] = relationship(back_populates="profile")
    background_tasks: Mapped[list[BackgroundTask]] = relationship(back_populates="profile")


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
    discovery_method: Mapped[str] = mapped_column(String(32), default="direct")
    score: Mapped[float | None] = mapped_column(Float)
    score_details: Mapped[dict] = mapped_column(JSON, default=dict)
    research: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="discovered")
    crm_stage: Mapped[str] = mapped_column(String(32), default="new")
    crm_notes: Mapped[str | None] = mapped_column(Text)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    applications: Mapped[list[ApplicationDraft]] = relationship(back_populates="job_lead")
    saved_search_matches: Mapped[list[SavedSearchMatch]] = relationship(back_populates="job_lead")


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
    background_tasks: Mapped[list[BackgroundTask]] = relationship(back_populates="application_draft")


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
    background_tasks: Mapped[list[BackgroundTask]] = relationship(back_populates="worker_run")


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("profile_id", "name", name="uq_saved_search_profile_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id"))
    name: Mapped[str] = mapped_column(String(255))
    search_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    cadence_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(32), default="idle")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="saved_searches")
    discovery_runs: Mapped[list[DiscoveryRun]] = relationship(back_populates="saved_search")
    matches: Mapped[list[SavedSearchMatch]] = relationship(back_populates="saved_search")
    background_tasks: Mapped[list[BackgroundTask]] = relationship(back_populates="saved_search")


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    saved_search_id: Mapped[int] = mapped_column(ForeignKey("saved_searches.id"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("candidate_profiles.id"))
    trigger_kind: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    model_name: Mapped[str | None] = mapped_column(String(128))
    search_preferences_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    search_queries: Mapped[list] = mapped_column(JSON, default=list)
    source_urls: Mapped[list] = mapped_column(JSON, default=list)
    grounded_pages_count: Mapped[int] = mapped_column(Integer, default=0)
    jobs_created_count: Mapped[int] = mapped_column(Integer, default=0)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    saved_search: Mapped[SavedSearch] = relationship(back_populates="discovery_runs")
    profile: Mapped[CandidateProfile] = relationship(back_populates="discovery_runs")
    matches: Mapped[list[SavedSearchMatch]] = relationship(back_populates="discovery_run")
    background_tasks: Mapped[list[BackgroundTask]] = relationship(back_populates="discovery_run")


class SavedSearchMatch(Base):
    __tablename__ = "saved_search_matches"
    __table_args__ = (UniqueConstraint("saved_search_id", "job_lead_id", name="uq_saved_search_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    saved_search_id: Mapped[int] = mapped_column(ForeignKey("saved_searches.id"))
    job_lead_id: Mapped[int] = mapped_column(ForeignKey("job_leads.id"))
    discovery_run_id: Mapped[int | None] = mapped_column(ForeignKey("discovery_runs.id"))
    current_score: Mapped[float | None] = mapped_column(Float)
    score_details: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback_state: Mapped[str] = mapped_column(String(32), default="neutral")
    feedback_note: Mapped[str | None] = mapped_column(Text)
    last_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    saved_search: Mapped[SavedSearch] = relationship(back_populates="matches")
    job_lead: Mapped[JobLead] = relationship(back_populates="saved_search_matches")
    discovery_run: Mapped[DiscoveryRun | None] = relationship(back_populates="matches")
    feedback_events: Mapped[list[SearchFeedbackEvent]] = relationship(back_populates="saved_search_match")


class SearchFeedbackEvent(Base):
    __tablename__ = "search_feedback_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    saved_search_match_id: Mapped[int] = mapped_column(ForeignKey("saved_search_matches.id"))
    signal: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    saved_search_match: Mapped[SavedSearchMatch] = relationship(back_populates="feedback_events")


class BackgroundTask(Base):
    __tablename__ = "background_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_profiles.id"))
    saved_search_id: Mapped[int | None] = mapped_column(ForeignKey("saved_searches.id"))
    discovery_run_id: Mapped[int | None] = mapped_column(ForeignKey("discovery_runs.id"))
    application_draft_id: Mapped[int | None] = mapped_column(ForeignKey("application_drafts.id"))
    worker_run_id: Mapped[int | None] = mapped_column(ForeignKey("worker_runs.id"))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    profile: Mapped[CandidateProfile | None] = relationship(back_populates="background_tasks")
    saved_search: Mapped[SavedSearch | None] = relationship(back_populates="background_tasks")
    discovery_run: Mapped[DiscoveryRun | None] = relationship(back_populates="background_tasks")
    application_draft: Mapped[ApplicationDraft | None] = relationship(back_populates="background_tasks")
    worker_run: Mapped[WorkerRun | None] = relationship(back_populates="background_tasks")
