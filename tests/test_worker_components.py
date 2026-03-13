from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

from apps.api.app.schemas import (
    ApplicationDraftWorkerPayload,
    CandidateProfilePayload,
    JobLeadWorkerPayload,
    WorkerAnswerOverride,
    WorkerFieldOption,
    WorkerFieldState,
    WorkerRunRequest,
)
from apps.api.app.services.llm.base import DisabledLLMClient, DraftedAnswerSuggestion
from apps.worker.answer_resolver import build_preview_summary, resolve_fields
from apps.worker.field_classifier import classify_field
from apps.worker.form_extractor import extract_form_fields
from apps.worker.main import _resolve_selector, _should_capture_screenshot
from apps.worker.platform_adapters import detect_platform


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


def test_detect_platform_recognizes_ashbyhq_urls():
    assert (
        detect_platform("https://jobs.ashbyhq.com/Ashby/1234-support-engineer/application", "generic")
        == "ashbyhq"
    )


def test_should_capture_screenshot_only_for_failures_and_submission_states():
    assert _should_capture_screenshot("failed") is True
    assert _should_capture_screenshot("submit_failed") is True
    assert _should_capture_screenshot("verification_required") is True
    assert _should_capture_screenshot("submit_clicked") is True
    assert _should_capture_screenshot("submitted") is True
    assert _should_capture_screenshot("preview_ready") is False
    assert _should_capture_screenshot("awaiting_answers") is False
    assert _should_capture_screenshot("ready_for_submit") is False


def test_extract_form_fields_prefers_structural_selector_attributes():
    fixture_html = """
    <form>
      <label for="office-attendance">Office attendance</label>
      <select
        id="office-attendance"
        data-testid="office-attendance-select"
        aria-label="Are you open to working in-person in one of our offices 25% of the time?"
      >
        <option value="">Select...</option>
        <option value="yes">Yes</option>
        <option value="no">No</option>
      </select>
    </form>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(fixture_html, wait_until="load")
        fields = extract_form_fields(page)
        browser.close()

    office_field = next(field for field in fields if field.field_id == "office-attendance")
    assert office_field.selector == "#office-attendance"
    assert office_field.selector_candidates[:3] == [
        "#office-attendance",
        'select[data-testid="office-attendance-select"]',
        'select[aria-label="Are you open to working in-person in one of our offices 25% of the time?"]',
    ]


def test_extract_form_fields_reads_custom_combobox_and_radiogroup():
    fixture_html = """
    <form>
      <label id="attendance-label">Office attendance</label>
      <button
        id="office-attendance"
        type="button"
        role="combobox"
        aria-controls="attendance-list"
        aria-labelledby="attendance-label office-attendance"
      >
        Select...
      </button>
      <ul id="attendance-list" role="listbox" hidden>
        <li role="option" data-value="yes">Yes</li>
        <li role="option" data-value="no">No</li>
      </ul>

      <div id="visa-sponsorship" role="radiogroup" aria-label="Do you require visa sponsorship?">
        <button type="button" role="radio" data-value="yes">Yes</button>
        <button type="button" role="radio" data-value="no">No</button>
      </div>
    </form>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(fixture_html, wait_until="load")
        fields = extract_form_fields(page)
        browser.close()

    attendance_field = next(field for field in fields if field.field_id == "office-attendance")
    visa_field = next(field for field in fields if field.field_id == "visa-sponsorship")

    assert attendance_field.field_type == "select"
    assert attendance_field.input_type == "combobox"
    assert [option.label for option in attendance_field.options] == ["Yes", "No"]
    assert visa_field.field_type == "radio"
    assert visa_field.input_type == "radiogroup"
    assert [option.value for option in visa_field.options] == ["yes", "no"]


def test_extract_form_fields_reads_hidden_native_radio_fieldset():
    fixture_html = """
    <form>
      <fieldset>
        <label class="question-title" for="hear-about-elevenlabs">
          How did you hear about ElevenLabs?
        </label>
        <div>
          <span><input type="radio" id="hear-about-user" name="hear-about" required style="position:absolute; opacity:0; width:0; height:0;" /></span>
          <label for="hear-about-user">I'm a user</label>
        </div>
        <div>
          <span><input type="radio" id="hear-about-news" name="hear-about" style="position:absolute; opacity:0; width:0; height:0;" /></span>
          <label for="hear-about-news">News article</label>
        </div>
        <div>
          <span><input type="radio" id="hear-about-other" name="hear-about" style="position:absolute; opacity:0; width:0; height:0;" /></span>
          <label for="hear-about-other">Other (please specify)</label>
        </div>
      </fieldset>
      <label for="hear-about-detail">If other, please specify below</label>
      <input id="hear-about-detail" name="hear-about-detail" placeholder="Type here..." />
    </form>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(fixture_html, wait_until="load")
        fields = extract_form_fields(page)
        browser.close()

    source_field = next(
        field
        for field in fields
        if field.label == "How did you hear about ElevenLabs?"
    )

    assert source_field.field_type == "radio"
    assert source_field.input_type == "radiogroup"
    assert [option.label for option in source_field.options] == [
        "I'm a user",
        "News article",
        "Other (please specify)",
    ]
    assert source_field.options[0].selector == 'label[for="hear-about-user"]'


def test_extract_form_fields_reads_react_select_input_combobox_and_skips_shadow_placeholder():
    fixture_html = """
    <form>
      <label id="question_1-label" for="question_1">Are you open to working in-person?</label>
      <div class="select__value-container">
        <div class="select__placeholder" id="react-select-question_1-placeholder">Select...</div>
        <div class="select__input-container" data-value="">
          <input
            id="question_1"
            type="text"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded="false"
            aria-haspopup="true"
            aria-labelledby="question_1-label"
            aria-describedby="react-select-question_1-placeholder"
          />
        </div>
      </div>

      <div class="shadow-wrapper">
        <input type="text" role="combobox" aria-expanded="false" aria-haspopup="true" value="" />
      </div>

      <script>
        const input = document.getElementById('question_1')
        input.addEventListener('click', () => {
          input.setAttribute('aria-expanded', 'true')
          if (document.getElementById('react-select-question_1-listbox')) return
          const listbox = document.createElement('div')
          listbox.id = 'react-select-question_1-listbox'
          listbox.setAttribute('role', 'listbox')
          const yes = document.createElement('div')
          yes.id = 'react-select-question_1-option-0'
          yes.setAttribute('role', 'option')
          yes.textContent = 'Yes'
          const no = document.createElement('div')
          no.id = 'react-select-question_1-option-1'
          no.setAttribute('role', 'option')
          no.textContent = 'No'
          listbox.appendChild(yes)
          listbox.appendChild(no)
          document.body.appendChild(listbox)
        })
      </script>
    </form>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(fixture_html, wait_until="load")
        fields = extract_form_fields(page)
        browser.close()

    attendance_field = next(field for field in fields if field.field_id == "question-1")

    assert attendance_field.field_type == "select"
    assert attendance_field.input_type == "combobox"
    assert [option.label for option in attendance_field.options] == ["Yes", "No"]
    assert not any(field.question_text == "Select..." and field.label == "" for field in fields)


def test_resolve_selector_uses_extracted_candidate_fallbacks_before_platform_hints():
    fixture_html = """
    <form>
      <input name="candidate_email" autocomplete="email" />
    </form>
    """

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(fixture_html, wait_until="load")
        field = WorkerFieldState(
            field_id="email",
            label="Email",
            question_text="Email",
            selector='input[data-testid="missing-email"]',
            selector_candidates=[
                'input[data-testid="missing-email"]',
                'input[name="candidate_email"]',
                'input[autocomplete="email"]',
            ],
            field_type="text",
            canonical_key="email",
            html_name="candidate_email",
            required=True,
        )

        resolved_selector = _resolve_selector(page, "greenhouse", field)
        browser.close()

    assert resolved_selector == 'input[name="candidate_email"]'


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


def test_classify_field_does_not_map_choice_question_from_option_labels():
    field = WorkerFieldState(
        field_id="hear-about-elevenlabs",
        label="How did you hear about ElevenLabs?",
        question_text=(
            "How did you hear about ElevenLabs? "
            "I'm a user News article Job board Social media (LinkedIn, Instagram, X etc)"
        ),
        selector="#hear-about-elevenlabs",
        field_type="radio",
        input_type="radiogroup",
        required=True,
        options=[
            WorkerFieldOption(label="I'm a user", value="I'm a user"),
            WorkerFieldOption(label="News article", value="News article"),
            WorkerFieldOption(label="Job board", value="Job board"),
            WorkerFieldOption(
                label="Social media (LinkedIn, Instagram, X etc)",
                value="Social media (LinkedIn, Instagram, X etc)",
            ),
        ],
    )

    classified = classify_field(field, "ashbyhq", DisabledLLMClient())

    assert classified.canonical_key == "custom_question"
    assert classified.classification_source == "fallback"


def test_classify_field_detects_phone_country_code_combobox():
    field = WorkerFieldState(
        field_id="country",
        label="Country",
        question_text="Country Phone",
        selector="#country",
        field_type="select",
        input_type="combobox",
        html_id="country",
        options=[
            WorkerFieldOption(label="United States +1", value="United States +1"),
            WorkerFieldOption(label="France +33", value="France +33"),
            WorkerFieldOption(label="United Kingdom +44", value="United Kingdom +44"),
            WorkerFieldOption(label="Germany +49", value="Germany +49"),
            WorkerFieldOption(label="Spain +34", value="Spain +34"),
            WorkerFieldOption(label="Italy +39", value="Italy +39"),
            WorkerFieldOption(label="Portugal +351", value="Portugal +351"),
            WorkerFieldOption(label="Netherlands +31", value="Netherlands +31"),
            WorkerFieldOption(label="Belgium +32", value="Belgium +32"),
            WorkerFieldOption(label="Ireland +353", value="Ireland +353"),
            WorkerFieldOption(label="Sweden +46", value="Sweden +46"),
            WorkerFieldOption(label="Norway +47", value="Norway +47"),
            WorkerFieldOption(label="Denmark +45", value="Denmark +45"),
            WorkerFieldOption(label="Finland +358", value="Finland +358"),
            WorkerFieldOption(label="Poland +48", value="Poland +48"),
            WorkerFieldOption(label="Austria +43", value="Austria +43"),
            WorkerFieldOption(label="Switzerland +41", value="Switzerland +41"),
            WorkerFieldOption(label="Czechia +420", value="Czechia +420"),
            WorkerFieldOption(label="Romania +40", value="Romania +40"),
            WorkerFieldOption(label="Greece +30", value="Greece +30"),
        ],
    )

    classified = classify_field(field, "greenhouse", DisabledLLMClient())

    assert classified.canonical_key == "phone_country_code"
    assert classified.classification_source == "heuristic"
    assert classified.classification_confidence >= 0.9


def test_classify_field_does_not_map_cover_letter_file_upload_to_cover_note():
    field = WorkerFieldState(
        field_id="cover-letter",
        label="Cover Letter",
        question_text="Upload a cover letter",
        selector="#cover_letter",
        field_type="file",
        input_type="file",
        html_name="cover_letter",
        html_id="cover_letter",
    )

    classified = classify_field(field, "greenhouse", DisabledLLMClient())

    assert classified.canonical_key is None
    assert classified.classification_source == "unclassified"


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


def test_resolve_fields_matches_phone_country_code_from_phone_and_location():
    request = WorkerRunRequest(
        application_draft_id=1,
        target_url="https://example.com/jobs/1",
        platform="greenhouse",
        profile=CandidateProfilePayload(
            full_name="Paul Example",
            email="paul@example.com",
            phone="+44 75417 54049",
            location="London, UK",
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
        answer_overrides=[],
    )
    field = WorkerFieldState(
        field_id="country",
        label="Country",
        question_text="Country Phone",
        selector="#country",
        field_type="select",
        input_type="combobox",
        canonical_key="phone_country_code",
        options=[
            WorkerFieldOption(label="United States +1", value="United States +1"),
            WorkerFieldOption(label="Guernsey +44", value="Guernsey +44"),
            WorkerFieldOption(label="Jersey +44", value="Jersey +44"),
            WorkerFieldOption(label="United Kingdom +44", value="United Kingdom +44"),
        ],
    )

    resolved = resolve_fields(request, [field], FakeLLMClient())

    assert resolved[0].answer_value == "United Kingdom +44"
    assert resolved[0].answer_source == "profile"
    assert resolved[0].requires_review is False


def test_resolve_fields_does_not_apply_cover_note_text_to_file_upload():
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
        answer_overrides=[],
    )
    field = WorkerFieldState(
        field_id="cover-letter",
        label="Cover Letter",
        question_text="Upload a cover letter",
        selector="#cover_letter",
        field_type="file",
        input_type="file",
        canonical_key="cover_note",
        required=False,
    )

    resolved = resolve_fields(request, [field], FakeLLMClient())

    assert resolved[0].answer_value is None
    assert resolved[0].answer_source is None
    assert resolved[0].requires_review is False


def test_resolve_fields_keeps_required_choice_questions_structured_for_review():
    request = WorkerRunRequest(
        application_draft_id=1,
        target_url="https://example.com/jobs/1",
        platform="greenhouse",
        profile=CandidateProfilePayload(
            full_name="Paul Example",
            email="paul@example.com",
            location="London, UK",
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
        answer_overrides=[],
    )
    field = WorkerFieldState(
        field_id="office-attendance",
        label="Office attendance",
        question_text="Are you open to working in-person in one of our offices 25% of the time?",
        selector="#office-attendance",
        field_type="select",
        canonical_key="custom_question",
        required=True,
        options=[
            WorkerFieldOption(label="Yes", value="yes", selector="#office-attendance"),
            WorkerFieldOption(label="No", value="no", selector="#office-attendance"),
        ],
    )

    resolved = resolve_fields(request, [field], FakeLLMClient())

    assert resolved[0].answer_value is None
    assert resolved[0].answer_source is None
    assert resolved[0].requires_review is True
    assert "selection" in (resolved[0].review_reason or "").lower()
