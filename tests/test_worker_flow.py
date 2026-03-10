from __future__ import annotations

from pathlib import Path

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


def test_worker_submit_with_review_overrides_submits_greenhouse_form(client):
    seed_profile(client)
    job_id = create_job(
        source="greenhouse",
        url="https://boards.greenhouse.io/example-company/jobs/fixture-2",
    )

    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft = draft_response.json()

    fixture_html = (Path(__file__).parent / "fixtures" / "greenhouse_form.html").read_text()
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


def create_job(*, source: str, url: str) -> int:
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
            score=88.0,
            score_details={"summary": "High fit"},
            research={},
            status="discovered",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id
