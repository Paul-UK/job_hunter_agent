from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from apps.api.app.schemas import (
    ApplicationDraftWorkerPayload,
    CandidateProfilePayload,
    JobLeadWorkerPayload,
    WorkerAnswerOverride,
    WorkerFieldState,
    WorkerRunRequest,
)
from apps.api.app.services.llm.base import DisabledLLMClient, DraftedAnswerSuggestion
from apps.worker.answer_resolver import build_preview_summary, resolve_fields
from apps.worker.field_classifier import classify_field
from apps.worker.form_extractor import extract_form_fields


class FakeLLMClient:
    def is_enabled(self) -> bool:
        return True

    def classify_field(self, **_kwargs):
        return None

    def draft_long_form_answer(self, **_kwargs):
        return DraftedAnswerSuggestion(
            answer="I care about building reliable AI support experiences that help real customers.",
            confidence=0.81,
            reasoning="LLM suggested a first-pass answer.",
        )


def test_extract_form_fields_reads_greenhouse_fixture():
    fixture_html = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(fixture_html, wait_until="load")
        fields = extract_form_fields(page)
        browser.close()

    field_ids = {field.field_id for field in fields}
    assert "email" in field_ids
    assert "question-work-auth" in field_ids
    assert "question-why-anthropic" in field_ids
    assert any(field.field_type == "select" for field in fields)
    assert any(field.field_type == "textarea" for field in fields)


def test_classify_field_maps_email_from_realistic_metadata():
    field = WorkerFieldState(
        field_id="email",
        label="Email",
        question_text="Email",
        selector="#email",
        field_type="text",
        input_type="text",
        html_name="candidate_email",
        html_id="email",
    )

    classified = classify_field(field, "greenhouse", DisabledLLMClient())

    assert classified.canonical_key == "email"
    assert classified.classification_source == "heuristic"
    assert classified.classification_confidence >= 0.9


def test_resolve_fields_prefers_override_and_tracks_preview_summary():
    request = WorkerRunRequest(
        application_draft_id=1,
        target_url="https://example.com/jobs/1",
        platform="greenhouse",
        profile=CandidateProfilePayload(
            full_name="Paul Example",
            email="paul@example.com",
            location="London, UK",
            links={"resume_path": "/tmp/resume.txt"},
        ),
        job=JobLeadWorkerPayload(
            source="greenhouse",
            company="Example Company",
            title="AI Support Engineer",
            location="London, UK",
            employment_type="Hybrid",
            url="https://example.com/jobs/1",
            description="Support AI applications.",
            requirements=[],
            metadata_json={},
        ),
        draft=ApplicationDraftWorkerPayload(
            tailored_summary="Strong fit",
            cover_note="I want to help teams ship reliable AI support experiences.",
            resume_bullets=[],
            screening_answers=[],
        ),
        answer_overrides=[
            WorkerAnswerOverride(
                field_id="question-why-anthropic",
                value="Anthropic works on high-impact AI systems where strong support matters.",
            )
        ],
    )
    fields = [
        WorkerFieldState(
            field_id="email",
            label="Email",
            question_text="Email",
            selector="#email",
            field_type="text",
            canonical_key="email",
            required=True,
        ),
        WorkerFieldState(
            field_id="question-why-anthropic",
            label="Why Anthropic?",
            question_text="Why Anthropic?",
            selector="#question_why_anthropic",
            field_type="textarea",
            canonical_key="custom_question",
            required=True,
        ),
    ]

    resolved = resolve_fields(request, fields, FakeLLMClient())
    preview_summary = build_preview_summary(resolved)

    assert resolved[0].answer_value == "paul@example.com"
    assert resolved[0].requires_review is False
    assert resolved[1].answer_source == "user_override"
    assert resolved[1].requires_review is False
    assert preview_summary.unresolved_required_count == 0
    assert preview_summary.autofill_ready_count == 2
