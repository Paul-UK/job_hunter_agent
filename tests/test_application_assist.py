from __future__ import annotations

from apps.api.app.db import SessionLocal
from apps.api.app.models import JobLead
from apps.api.app.services.llm.base import DraftedAnswerSuggestion


class FakeLLMClient:
    def is_enabled(self) -> bool:
        return True

    def draft_application_material(self, **kwargs):
        if kwargs["material_type"] == "cover_note":
            return DraftedAnswerSuggestion(
                answer="I am excited to bring Python, SQL, and applied AI delivery experience to this team.",
                confidence=0.91,
                reasoning="Grounded cover note rewrite.",
            )
        question = kwargs.get("question") or "this role"
        return DraftedAnswerSuggestion(
            answer=f"I am interested because my support and AI background fits {question}.",
            confidence=0.86,
            reasoning="Grounded question answer rewrite.",
        )


def test_application_assist_rewrites_cover_note_and_persists(client, monkeypatch):
    monkeypatch.setattr("apps.api.app.routers.applications.get_llm_client", lambda: FakeLLMClient())
    seed_profile(client)
    job_id = create_job()
    draft = client.post(f"/api/jobs/{job_id}/draft").json()

    response = client.post(
        f"/api/applications/{draft['id']}/assist",
        json={
            "target": "cover_note",
            "current_text": draft["cover_note"],
            "persist": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"].startswith("I am excited to bring Python, SQL")
    assert payload["updated_draft"]["cover_note"] == payload["text"]


def test_application_assist_adds_custom_question_answer_to_draft(client, monkeypatch):
    monkeypatch.setattr("apps.api.app.routers.applications.get_llm_client", lambda: FakeLLMClient())
    seed_profile(client)
    job_id = create_job()
    draft = client.post(f"/api/jobs/{job_id}/draft").json()

    response = client.post(
        f"/api/applications/{draft['id']}/assist",
        json={
            "target": "question_answer",
            "question": "Why do you want to join this team?",
            "current_text": "",
            "persist": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Why do you want to join this team?" in {
        answer["question"] for answer in payload["updated_draft"]["screening_answers"]
    }
    assert any(
        answer["answer"] == payload["text"]
        for answer in payload["updated_draft"]["screening_answers"]
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
            "links": {},
        },
    )
    assert profile_response.status_code == 200


def create_job() -> int:
    with SessionLocal() as session:
        job = JobLead(
            source="greenhouse",
            external_id="assist-fixture",
            company="Example Company",
            title="AI Support Engineer",
            location="London, UK",
            employment_type="Hybrid",
            url="https://boards.greenhouse.io/example-company/jobs/assist-fixture",
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
