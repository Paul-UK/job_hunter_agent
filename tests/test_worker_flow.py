from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from apps.api.app.db import SessionLocal
from apps.api.app.models import JobLead
from apps.api.app.services.llm.base import DraftedAnswerSuggestion


class FakeLLMClient:
    def is_enabled(self) -> bool:
        return True

    def classify_field(self, **_kwargs):
        return None

    def draft_long_form_answer(self, **kwargs):
        company = kwargs["company"]
        return DraftedAnswerSuggestion(
            answer=f"I want to contribute to {company} by bringing practical support and AI experience.",
            confidence=0.84,
            reasoning="Gemini suggested a concise tailored answer.",
        )


def test_worker_preview_extracts_semantic_greenhouse_fields(client, monkeypatch):
    monkeypatch.setattr("apps.worker.main.get_llm_client", lambda: FakeLLMClient())
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-1",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    fixture_html = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={"dry_run": True, "fixture_html": fixture_html},
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "awaiting_answers"
    assert worker_run["preview_summary"]["autofill_ready_count"] >= 6
    assert worker_run["preview_summary"]["review_required_count"] >= 2
    assert any("Extracted" in log for log in worker_run["logs"])

    email_field = next(field for field in worker_run["fields"] if field["canonical_key"] == "email")
    assert email_field["selector"] == "#email"
    assert email_field["answer_value"] == "paul@example.com"
    assert email_field["requires_review"] is False

    why_anthropic = next(field for field in worker_run["review_items"] if field["field_id"] == "question-why-anthropic")
    assert why_anthropic["answer_source"] == "gemini"
    assert why_anthropic["requires_review"] is True
    assert worker_run["screenshot_path"] is None


def test_worker_preview_does_not_capture_screenshot(client, monkeypatch):
    monkeypatch.setattr("apps.worker.main.get_llm_client", lambda: FakeLLMClient())

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("_save_screenshot should not be called for preview or review runs")

    monkeypatch.setattr("apps.worker.main._save_screenshot", fail_if_called)
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-preview-no-shot",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    fixture_html = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={"dry_run": True, "fixture_html": fixture_html},
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "awaiting_answers"
    assert worker_run["screenshot_path"] is None


def test_worker_submit_with_review_overrides_submits_greenhouse_form(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-2",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    fixture_html = confirmed_greenhouse_submit_fixture_html()
    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": fixture_html,
            "answer_overrides": [
                {"field_id": "question-work-auth", "value": "Yes"},
                {
                    "field_id": "question-why-anthropic",
                    "value": "Anthropic sits at the intersection of AI quality, support, and real customer impact.",
                },
            ],
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "submitted"
    assert worker_run["preview_summary"]["unresolved_required_count"] == 0
    assert any(action["field"] == "work_authorization" for action in worker_run["actions"])
    assert any(action["field"] == "custom_question" for action in worker_run["actions"])
    assert any("confirmation" in log.lower() for log in worker_run["logs"])

    with SessionLocal() as session:
        job = session.execute(select(JobLead).where(JobLead.id == job_id)).scalar_one()
        assert job.status == "submitted"


def test_worker_submission_captures_screenshot(client, monkeypatch):
    monkeypatch.setattr("apps.worker.main._save_screenshot", lambda _page, _platform: "/tmp/submitted-shot.png")
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-submit-shot",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": confirmed_greenhouse_submit_fixture_html(),
            "answer_overrides": [
                {"field_id": "question-work-auth", "value": "Yes"},
                {
                    "field_id": "question-why-anthropic",
                    "value": "Anthropic sits at the intersection of AI quality, support, and real customer impact.",
                },
            ],
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "submitted"
    assert worker_run["screenshot_path"] == "/tmp/submitted-shot.png"


def test_worker_submit_without_confirmation_marks_submit_clicked(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-2b",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": unconfirmed_greenhouse_submit_fixture_html(),
            "answer_overrides": [
                {"field_id": "question-work-auth", "value": "Yes"},
                {
                    "field_id": "question-why-anthropic",
                    "value": "Anthropic sits at the intersection of AI quality, support, and real customer impact.",
                },
            ],
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "submit_clicked"
    assert any("clicked submit" in log.lower() for log in worker_run["logs"])
    assert any("confirmation was not detected" in log.lower() for log in worker_run["logs"])

    with SessionLocal() as session:
        job = session.execute(select(JobLead).where(JobLead.id == job_id)).scalar_one()
        assert job.status == "submit_clicked"


def test_worker_submit_with_verification_requirement_marks_verification_required(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-2b-verification",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": verification_required_greenhouse_submit_fixture_html(),
            "answer_overrides": [
                {"field_id": "question-work-auth", "value": "Yes"},
                {
                    "field_id": "question-why-anthropic",
                    "value": "Anthropic sits at the intersection of AI quality, support, and real customer impact.",
                },
            ],
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "verification_required"
    assert any("verification" in log.lower() for log in worker_run["logs"])

    with SessionLocal() as session:
        job = session.execute(select(JobLead).where(JobLead.id == job_id)).scalar_one()
        assert job.status == "verification_required"


def test_worker_submit_with_invalid_form_bounce_marks_submit_failed(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-2c",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": invalid_greenhouse_submit_fixture_html(),
            "answer_overrides": [
                {"field_id": "question-work-auth", "value": "Yes"},
                {
                    "field_id": "question-why-anthropic",
                    "value": "Anthropic sits at the intersection of AI quality, support, and real customer impact.",
                },
            ],
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "submit_failed"
    assert any("clicked submit" in log.lower() for log in worker_run["logs"])
    assert any("form still appears invalid" in log.lower() for log in worker_run["logs"])

    with SessionLocal() as session:
        job = session.execute(select(JobLead).where(JobLead.id == job_id)).scalar_one()
        assert job.status == "submit_failed"


def test_worker_preview_handles_lever_form_and_flags_missing_answers(client, monkeypatch):
    monkeypatch.setattr("apps.worker.main.get_llm_client", lambda: FakeLLMClient())
    seed_profile(client)
    job_id = create_job(
        source="lever",
        url="https://jobs.lever.co/example-company/fixture-3",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    fixture_html = (Path(__file__).parent / "fixtures" / "lever_form.html").read_text()
    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={"dry_run": True, "fixture_html": fixture_html},
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "awaiting_answers"
    assert any(field["canonical_key"] == "email" for field in worker_run["fields"])
    assert any(field["canonical_key"] == "linkedin" for field in worker_run["fields"])
    assert any(field["canonical_key"] == "start_date" for field in worker_run["review_items"])
    assert any(field["field_id"] == "question-why-role" for field in worker_run["review_items"])


def test_worker_preview_uses_platform_for_web_discovered_greenhouse_job(client, monkeypatch):
    monkeypatch.setattr("apps.worker.main.get_llm_client", lambda: FakeLLMClient())
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/web-discovered-1",
        discovery_method="gemini_grounded_search",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    fixture_html = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={"dry_run": True, "fixture_html": fixture_html},
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["platform"] == "greenhouse"
    assert worker_run["target_url"] == "https://boards.greenhouse.io/example-company/jobs/web-discovered-1"


def test_worker_submit_handles_custom_choice_widgets(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/custom-choice-fixture",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": custom_choice_fixture_html(),
            "answer_overrides": [
                {"field_id": "office-attendance", "value": "Yes"},
                {"field_id": "visa-sponsorship", "value": "No"},
            ],
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "submitted"
    assert any(action["mode"] == "choose" for action in worker_run["actions"])
    assert any(action["mode"] == "click" for action in worker_run["actions"])


def test_worker_submit_handles_greenhouse_location_autocomplete(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/location-autocomplete-fixture",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": greenhouse_location_autocomplete_fixture_html(),
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "submitted"
    assert any(action["field"] == "location" and action["mode"] == "autocomplete" for action in worker_run["actions"])


def test_worker_submit_handles_hidden_native_radio_fieldset(client, monkeypatch):
    monkeypatch.setattr("apps.worker.main.get_llm_client", lambda: FakeLLMClient())
    seed_profile(client)
    job_id = create_job(
        source="ashbyhq",
        url="https://jobs.ashbyhq.com/example-company/hidden-native-radio/application",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    preview_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={"dry_run": True, "fixture_html": hidden_native_choice_fixture_html()},
    )
    assert preview_response.status_code == 200
    preview_run = preview_response.json()
    assert preview_run["status"] == "awaiting_answers"

    source_field = next(
        field
        for field in preview_run["review_items"]
        if field["label"] == "How did you hear about ElevenLabs?"
    )

    submit_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": hidden_native_choice_fixture_html(),
            "answer_overrides": [
                {"field_id": source_field["field_id"], "value": "News article"},
            ],
        },
    )
    assert submit_response.status_code == 200
    worker_run = submit_response.json()

    assert worker_run["status"] == "submitted"
    radio_action = next(
        action for action in worker_run["actions"] if action["field_id"] == source_field["field_id"]
    )
    assert radio_action["mode"] == "click"
    assert radio_action["selector"] == 'label[for="hear-about-news"]'


def test_worker_skips_submit_when_custom_choice_cannot_be_applied(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/custom-choice-fixture-fail",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={
            "dry_run": False,
            "confirm_submit": True,
            "fixture_html": custom_choice_fixture_html(),
            "answer_overrides": [
                {"field_id": "office-attendance", "value": "Maybe"},
                {"field_id": "visa-sponsorship", "value": "No"},
            ],
        },
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    assert worker_run["status"] == "ready_for_submit"
    assert any("skipped final submit" in log.lower() for log in worker_run["logs"])


def test_worker_preview_extracts_react_select_combobox_as_structured_choice(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/react-select-fixture",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    worker_response = client.post(
        f"/api/applications/{draft['id']}/run",
        json={"dry_run": True, "fixture_html": react_select_fixture_html()},
    )
    assert worker_response.status_code == 200
    worker_run = worker_response.json()

    attendance_field = next(
        field for field in worker_run["fields"] if field["field_id"] == "question-1"
    )

    assert attendance_field["field_type"] == "select"
    assert attendance_field["input_type"] == "combobox"
    assert [option["label"] for option in attendance_field["options"]] == ["Yes", "No"]
    assert not any(
        field["question_text"] == "Select..." and not field["label"]
        for field in worker_run["fields"]
    )


def seed_profile(client) -> None:
    cv_text = """
    Paul Example
    ML Support Engineering Leader
    paul@example.com
    London, UK

    Summary
    Support engineering leader with Python, SQL, and practical AI application experience.

    Skills
    Python, SQL, AWS, Playwright
    """.strip()

    cv_response = client.post(
        "/api/profile/cv",
        files={"file": ("resume.txt", cv_text.encode("utf-8"), "text/plain")},
    )
    assert cv_response.status_code == 200
    resume_path = cv_response.json()["merged_profile"]["links"]["resume_path"]

    profile_response = client.put(
        "/api/profile",
        json={
            "full_name": "Paul Example",
            "headline": "ML Support Engineering Leader",
            "email": "paul@example.com",
            "phone": "+44 7000 000000",
            "location": "London, UK",
            "summary": (
                "Support engineering leader with experience across Python, SQL, "
                "large-scale customer escalations, and AI operations."
            ),
            "skills": ["Python", "SQL", "AWS", "Playwright"],
            "achievements": [],
            "experiences": [],
            "education": [],
            "links": {
                "resume_path": resume_path,
                "linkedin": "https://www.linkedin.com/in/paul-example/",
                "github": "https://github.com/paul-example",
            },
        },
    )
    assert profile_response.status_code == 200


def create_job(*, source: str, url: str, discovery_method: str = "direct") -> int:
    with SessionLocal() as session:
        job = JobLead(
            source=source,
            external_id=f"{source}-fixture",
            company="Example Company",
            title="AI Support Engineer",
            location="London, UK",
            employment_type="Hybrid",
            url=url,
            description="Support AI applications with Python and SQL.",
            requirements=["Python", "SQL"],
            metadata_json={},
            discovery_method=discovery_method,
            score=88.0,
            score_details={"summary": "High fit"},
            research={},
            status="discovered",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def custom_choice_fixture_html() -> str:
    return """
    <html>
      <body>
        <form onsubmit="event.preventDefault(); document.body.dataset.submitted = 'true';">
          <label id="attendance-label">Are you open to working in-person in one of our offices 25% of the time?</label>
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

          <button type="submit">Submit Application</button>
        </form>

        <script>
          const attendanceButton = document.getElementById('office-attendance')
          const attendanceList = document.getElementById('attendance-list')
          attendanceButton.addEventListener('click', () => {
            attendanceList.hidden = false
          })
          for (const option of attendanceList.querySelectorAll('[role="option"]')) {
            option.addEventListener('click', () => {
              attendanceButton.textContent = option.textContent
              attendanceButton.dataset.value = option.dataset.value
              attendanceList.hidden = true
            })
          }

          for (const radio of document.querySelectorAll('[role="radio"]')) {
            radio.addEventListener('click', () => {
              for (const candidate of document.querySelectorAll('[role="radio"]')) {
                candidate.setAttribute('aria-checked', candidate === radio ? 'true' : 'false')
              }
            })
          }
        </script>
      </body>
    </html>
    """


def hidden_native_choice_fixture_html() -> str:
    return """
    <html>
      <body>
        <form onsubmit="event.preventDefault(); document.body.innerHTML = '<main><h1>Thank you for applying</h1><p>Your application has been submitted.</p></main>';">
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
              <span><input type="radio" id="hear-about-job-board" name="hear-about" style="position:absolute; opacity:0; width:0; height:0;" /></span>
              <label for="hear-about-job-board">Job board</label>
            </div>
          </fieldset>
          <label for="hear-about-detail">If other, please specify below</label>
          <input id="hear-about-detail" name="hear-about-detail" placeholder="Type here..." />

          <button type="submit">Submit Application</button>
        </form>
      </body>
    </html>
    """


def confirmed_greenhouse_submit_fixture_html() -> str:
    base_fixture = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
    return base_fixture.replace(
        "<form>",
        (
            "<form onsubmit=\"event.preventDefault(); "
            "document.body.innerHTML = '<main><h1>Thank you for applying</h1>"
            "<p>Your application has been submitted.</p></main>'; "
            "history.replaceState({}, '', '/applications/complete');\">"
        ),
        1,
    )


def unconfirmed_greenhouse_submit_fixture_html() -> str:
    base_fixture = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
    return base_fixture.replace(
        "<form>",
        (
            "<form onsubmit=\"event.preventDefault(); "
            "document.body.innerHTML = '<main><h1>We are processing your application</h1>"
            "<p>Your submission is being reviewed.</p></main>'; "
            "history.replaceState({}, '', '/applications/pending');\">"
        ),
        1,
    )


def verification_required_greenhouse_submit_fixture_html() -> str:
    base_fixture = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
    return base_fixture.replace(
        "<form>",
        (
            "<form onsubmit=\"event.preventDefault(); "
            "const notice = document.createElement('div'); "
            "notice.id = 'verification-notice'; "
            "notice.textContent = 'Check your email for a verification code to continue.'; "
            "document.body.prepend(notice);\">"
        ),
        1,
    )


def invalid_greenhouse_submit_fixture_html() -> str:
    base_fixture = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
    return base_fixture.replace(
        "<form>",
        (
            "<form onsubmit=\"event.preventDefault(); "
            "const error = document.createElement('div'); "
            "error.id = 'validation-error'; "
            "error.setAttribute('role', 'alert'); "
            "error.setAttribute('aria-invalid', 'true'); "
            "error.textContent = 'Please complete the required fields.'; "
            "document.body.appendChild(error);\">"
        ),
        1,
    )


def greenhouse_location_autocomplete_fixture_html() -> str:
    return """
    <html>
      <body>
        <form
          onsubmit="
            event.preventDefault();
            const selected = window.__selectedLocation || '';
            const input = document.getElementById('candidate-location');
            const error = document.getElementById('candidate-location-error');
            if (!selected) {
              input.setAttribute('aria-invalid', 'true');
              error.textContent = 'Please select a location from the list.';
              return;
            }
            document.body.dataset.submitted = 'true';
            document.body.innerHTML = '<main><h1>Thank you for applying</h1><p>Your application has been submitted.</p></main>';
          "
        >
          <label for="first_name">First Name*</label>
          <input id="first_name" name="first_name" required />

          <label for="last_name">Last Name*</label>
          <input id="last_name" name="last_name" required />

          <label for="email">Email*</label>
          <input id="email" name="email" type="email" required />

          <label id="candidate-location-label" for="candidate-location">Location (City)*</label>
          <div class="select__control">
            <div class="select__value-container" id="candidate-location-container">
              <input
                id="candidate-location"
                class="select__input"
                type="text"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded="false"
                aria-haspopup="true"
                aria-invalid="false"
                aria-labelledby="candidate-location-label"
                aria-errormessage="candidate-location-error"
                aria-describedby="candidate-location-error"
                aria-required="true"
                autocomplete="off"
              />
            </div>
          </div>
          <div id="candidate-location-error" role="alert"></div>

          <div id="react-select-candidate-location-listbox" role="listbox" hidden></div>

          <button type="submit">Submit Application</button>
        </form>

        <script>
          window.__selectedLocation = ''
          const input = document.getElementById('candidate-location')
          const listbox = document.getElementById('react-select-candidate-location-listbox')
          const container = document.getElementById('candidate-location-container')
          const options = [
            'London, England, United Kingdom',
            'London, Ontario, Canada',
            'New London, Connecticut, United States',
          ]

          const renderOptions = (query) => {
            const normalized = (query || '').trim().toLowerCase()
            listbox.innerHTML = ''
            if (!normalized) {
              listbox.hidden = true
              input.setAttribute('aria-expanded', 'false')
              return
            }

            const matches = options.filter((option) => option.toLowerCase().includes(normalized))
            if (!matches.length) {
              listbox.hidden = true
              input.setAttribute('aria-expanded', 'false')
              return
            }
            window.clearTimeout(window.__locationRenderTimer || 0)
            window.__locationRenderTimer = window.setTimeout(() => {
              matches.forEach((option, index) => {
                const node = document.createElement('div')
                node.id = `react-select-candidate-location-option-${index}`
                node.setAttribute('role', 'option')
                node.textContent = option
                node.addEventListener('click', () => {
                  window.__selectedLocation = option
                  input.value = ''
                  input.setAttribute('aria-invalid', 'false')
                  input.setAttribute('aria-expanded', 'false')
                  listbox.hidden = true
                  const existing = container.querySelector('.select__single-value')
                  if (existing) existing.remove()
                  const selected = document.createElement('div')
                  selected.className = 'select__single-value'
                  selected.textContent = option
                  container.prepend(selected)
                })
                listbox.appendChild(node)
              })

              listbox.hidden = false
              input.setAttribute('aria-expanded', 'true')
            }, 500)
          }

          input.addEventListener('input', (event) => {
            window.__selectedLocation = ''
            renderOptions(event.target.value)
          })
        </script>
      </body>
    </html>
    """


def react_select_fixture_html() -> str:
    return """
    <html>
      <body>
        <form>
          <label id="question_1-label" for="question_1">
            Are you open to working in-person in one of our offices 25% of the time?
          </label>
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
                aria-required="true"
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
      </body>
    </html>
    """
