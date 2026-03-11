from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ExperienceItem(BaseModel):
    company: str
    title: str | None = None
    duration: str | None = None
    highlights: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    institution: str
    degree: str | None = None
    details: str | None = None


class CandidateProfilePayload(BaseModel):
    full_name: str | None = None
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    experiences: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)


class ProfileSourcePayload(BaseModel):
    id: int | None = None
    source_type: Literal["cv", "linkedin"]
    source_label: str
    confidence: dict[str, float] = Field(default_factory=dict)
    payload: CandidateProfilePayload


class CandidateProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str | None = None
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    source_of_truth: str
    merged_profile: dict[str, Any]
    field_sources: dict[str, Any]


class ProfileUpdateRequest(CandidateProfilePayload):
    pass


class JobDiscoveryRequest(BaseModel):
    identifiers: list[str] = Field(default_factory=list)
    include_questions: bool = False


class JobLeadBulkDeleteRequest(BaseModel):
    job_ids: list[int] = Field(default_factory=list)


class LinkedinLeadRequest(BaseModel):
    company: str
    title: str
    url: HttpUrl | None = None
    location: str | None = None
    description: str | None = None
    notes: str | None = None


class JobLeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    company: str
    title: str
    location: str | None = None
    employment_type: str | None = None
    url: str
    description: str
    score: float | None = None
    status: str
    requirements: list[Any] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    score_details: dict[str, Any] = Field(default_factory=dict)
    research: dict[str, Any] = Field(default_factory=dict)


class RankingResult(BaseModel):
    score: float
    matched_skills: list[str] = Field(default_factory=list)
    matched_signals: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    summary: str


class ResearchResponse(BaseModel):
    company: str
    website_summary: str | None = None
    github_org: str | None = None
    github_summary: str | None = None
    top_languages: list[str] = Field(default_factory=list)
    notable_repos: list[dict[str, Any]] = Field(default_factory=list)


class ScreeningAnswerPayload(BaseModel):
    question: str
    answer: str


class ApplicationDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    job_lead_id: int
    tailored_summary: str
    cover_note: str
    resume_bullets: list[str] = Field(default_factory=list)
    screening_answers: list[ScreeningAnswerPayload] = Field(default_factory=list)
    status: str


class ApplicationDraftAssistRequest(BaseModel):
    target: Literal["cover_note", "question_answer"]
    question: str | None = None
    current_text: str | None = None
    persist: bool = True


class ApplicationDraftAssistResponse(BaseModel):
    text: str
    confidence: float
    reasoning: str
    updated_draft: ApplicationDraftResponse | None = None


class DeleteResponse(BaseModel):
    entity: Literal["job_lead", "application_draft", "worker_run", "profile_source"]
    deleted_id: int
    deleted_counts: dict[str, int] = Field(default_factory=dict)


class BulkDeleteResponse(BaseModel):
    entity: Literal["job_leads"]
    deleted_ids: list[int] = Field(default_factory=list)
    deleted_counts: dict[str, int] = Field(default_factory=dict)


class WorkerFieldOption(BaseModel):
    label: str
    value: str
    selector: str | None = None


class WorkerActionPayload(BaseModel):
    field: str
    selector: str
    value: str
    field_id: str | None = None
    mode: str = "fill"


class WorkerAnswerOverride(BaseModel):
    field_id: str
    value: str


class ApplicationDraftWorkerPayload(BaseModel):
    tailored_summary: str = ""
    cover_note: str = ""
    resume_bullets: list[str] = Field(default_factory=list)
    screening_answers: list[ScreeningAnswerPayload] = Field(default_factory=list)


class JobLeadWorkerPayload(BaseModel):
    source: str
    company: str
    title: str
    location: str | None = None
    employment_type: str | None = None
    url: HttpUrl
    description: str = ""
    requirements: list[Any] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class WorkerFieldState(BaseModel):
    field_id: str
    label: str = ""
    question_text: str = ""
    selector: str
    field_type: str
    input_type: str | None = None
    html_name: str | None = None
    html_id: str | None = None
    placeholder: str | None = None
    required: bool = False
    options: list[WorkerFieldOption] = Field(default_factory=list)
    section: str | None = None
    canonical_key: str | None = None
    canonical_label: str | None = None
    classification_confidence: float = 0.0
    classification_source: str | None = None
    classification_reasoning: str | None = None
    answer_value: str | None = None
    answer_source: str | None = None
    answer_confidence: float = 0.0
    requires_review: bool = False
    review_reason: str | None = None


class WorkerPreviewSummary(BaseModel):
    total_fields: int = 0
    autofill_ready_count: int = 0
    required_count: int = 0
    review_required_count: int = 0
    unresolved_required_count: int = 0
    llm_suggestions_count: int = 0


class WorkerRunRequest(BaseModel):
    target_url: HttpUrl
    platform: Literal["greenhouse", "lever", "generic"] = "generic"
    profile: CandidateProfilePayload
    job: JobLeadWorkerPayload
    draft: ApplicationDraftWorkerPayload
    answer_overrides: list[WorkerAnswerOverride] = Field(default_factory=list)
    dry_run: bool = True
    confirm_submit: bool = False
    application_draft_id: int | None = None
    fixture_html: str | None = None


class ApplicationRunRequest(BaseModel):
    dry_run: bool = True
    confirm_submit: bool = False
    fixture_html: str | None = None
    answer_overrides: list[WorkerAnswerOverride] = Field(default_factory=list)
    cover_note: str | None = None
    screening_answers: list[ScreeningAnswerPayload] | None = None


class WorkerRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_draft_id: int | None = None
    platform: str
    target_url: str
    dry_run: bool
    status: str
    actions: list[WorkerActionPayload] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None
    fields: list[WorkerFieldState] = Field(default_factory=list)
    review_items: list[WorkerFieldState] = Field(default_factory=list)
    preview_summary: WorkerPreviewSummary = Field(default_factory=WorkerPreviewSummary)
    profile_snapshot: dict[str, Any] = Field(default_factory=dict)
    job_snapshot: dict[str, Any] = Field(default_factory=dict)
    draft_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class DashboardResponse(BaseModel):
    profile: CandidateProfileResponse | None = None
    profile_sources: list[ProfileSourcePayload] = Field(default_factory=list)
    jobs: list[JobLeadResponse] = Field(default_factory=list)
    applications: list[ApplicationDraftResponse] = Field(default_factory=list)
    worker_runs: list[WorkerRunResponse] = Field(default_factory=list)
