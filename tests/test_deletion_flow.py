from __future__ import annotations

from sqlalchemy import select

from apps.api.app.config import settings
from apps.api.app.db import SessionLocal
from apps.api.app.models import ApplicationDraft, JobLead, WorkerRun


def test_delete_application_cascades_worker_runs(client):
    seed_profile(client)
    job_id = create_job()
    draft = client.post(f"/api/jobs/{job_id}/draft").json()
    create_worker_run(draft["id"])

    response = client.delete(f"/api/applications/{draft['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["entity"] == "application_draft"
    assert payload["deleted_counts"]["worker_runs"] == 1

    with SessionLocal() as session:
        assert session.execute(select(ApplicationDraft)).scalars().all() == []
        assert session.execute(select(WorkerRun)).scalars().all() == []
        assert len(session.execute(select(JobLead)).scalars().all()) == 1


def test_delete_job_cascades_drafts_and_worker_runs(client):
    seed_profile(client)
    job_id = create_job()
    draft = client.post(f"/api/jobs/{job_id}/draft").json()
    create_worker_run(draft["id"])

    response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["entity"] == "job_lead"
    assert payload["deleted_counts"]["application_drafts"] == 1
    assert payload["deleted_counts"]["worker_runs"] == 1

    with SessionLocal() as session:
        assert session.execute(select(JobLead)).scalars().all() == []
        assert session.execute(select(ApplicationDraft)).scalars().all() == []
        assert session.execute(select(WorkerRun)).scalars().all() == []


def test_delete_worker_run_preserves_draft(client):
    seed_profile(client)
    job_id = create_job()
    draft = client.post(f"/api/jobs/{job_id}/draft").json()
    run_id = create_worker_run(draft["id"])

    response = client.delete(f"/api/applications/runs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["entity"] == "worker_run"

    with SessionLocal() as session:
        assert len(session.execute(select(JobLead)).scalars().all()) == 1
        assert len(session.execute(select(ApplicationDraft)).scalars().all()) == 1
        assert session.execute(select(WorkerRun)).scalars().all() == []


def test_read_worker_run_screenshot_returns_artifact_file(client):
    seed_profile(client)
    job_id = create_job()
    draft = client.post(f"/api/jobs/{job_id}/draft").json()
    screenshot_dir = settings.artifacts_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / "worker-test-shot.png"
    screenshot_path.write_bytes(b"fake image bytes")
    run_id = create_worker_run(draft["id"], screenshot_path=str(screenshot_path))

    response = client.get(f"/api/applications/runs/{run_id}/screenshot")

    assert response.status_code == 200
    assert response.content == b"fake image bytes"


def test_bulk_delete_jobs_cascades_related_records(client):
    seed_profile(client)
    keep_job_id = create_job(external_id="delete-keep")
    delete_job_id_one = create_job(external_id="delete-bulk-1")
    delete_job_id_two = create_job(external_id="delete-bulk-2")

    draft_one = client.post(f"/api/jobs/{delete_job_id_one}/draft").json()
    draft_two = client.post(f"/api/jobs/{delete_job_id_two}/draft").json()
    create_worker_run(draft_one["id"])
    create_worker_run(draft_two["id"])

    response = client.post(
        "/api/jobs/bulk-delete",
        json={"job_ids": [delete_job_id_one, delete_job_id_two]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["entity"] == "job_leads"
    assert payload["deleted_counts"]["job_leads"] == 2
    assert payload["deleted_counts"]["application_drafts"] == 2
    assert payload["deleted_counts"]["worker_runs"] == 2

    with SessionLocal() as session:
        remaining_jobs = session.execute(select(JobLead)).scalars().all()
        assert [job.id for job in remaining_jobs] == [keep_job_id]
        assert session.execute(select(ApplicationDraft)).scalars().all() == []
        assert session.execute(select(WorkerRun)).scalars().all() == []


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


def create_job(*, external_id: str = "delete-fixture") -> int:
    with SessionLocal() as session:
        job = JobLead(
            source="greenhouse",
            external_id=external_id,
            company="Example Company",
            title="AI Support Engineer",
            location="London, UK",
            employment_type="Hybrid",
            url="https://boards.greenhouse.io/example-company/jobs/delete-fixture",
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


def create_worker_run(application_draft_id: int, *, screenshot_path: str | None = None) -> int:
    with SessionLocal() as session:
        worker_run = WorkerRun(
            application_draft_id=application_draft_id,
            platform="greenhouse",
            target_url="https://boards.greenhouse.io/example-company/jobs/delete-fixture",
            dry_run=True,
            status="preview_ready",
            actions=[],
            logs=["Preview generated."],
            fields=[],
            review_items=[],
            preview_summary={},
            profile_snapshot={},
            job_snapshot={},
            draft_snapshot={},
            screenshot_path=screenshot_path,
        )
        session.add(worker_run)
        session.commit()
        session.refresh(worker_run)
        return worker_run.id
