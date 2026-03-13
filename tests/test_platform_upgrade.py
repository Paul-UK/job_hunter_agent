from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from apps.api.app import db as db_module
from apps.api.app.db import SessionLocal
from apps.api.app.models import (
    ApplicationDraft,
    BackgroundTask,
    DiscoveryRun,
    JobLead,
    SavedSearch,
    SavedSearchMatch,
    WorkerRun,
)
from apps.api.app.services.job_discovery.service import WebDiscoveryResult


def seed_profile(client) -> None:
    response = client.put(
        "/api/profile",
        json={
            "full_name": "Paul Example",
            "headline": "Support Engineering Manager",
            "email": "paul@example.com",
            "phone": None,
            "location": "London, UK",
            "summary": "Support engineering leader for AI infrastructure and SaaS platforms.",
            "skills": ["Python", "SQL", "incident management"],
            "achievements": [],
            "experiences": [],
            "education": [],
            "links": {},
        },
    )
    assert response.status_code == 200


def create_job(client) -> int:
    response = client.post(
        "/api/jobs/discover/linkedin",
        json={
            "company": "Anthropic",
            "title": "Support Engineering Manager",
            "url": "https://boards.greenhouse.io/example-company/jobs/platform-upgrade-1",
            "location": "London, UK",
            "description": "Lead support engineering teams for AI infrastructure products.",
            "notes": None,
        },
    )
    assert response.status_code == 200
    return int(response.json()["id"])


def test_dashboard_exposes_default_saved_search(client):
    seed_profile(client)

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    dashboard = response.json()

    assert len(dashboard["saved_searches"]) == 1
    assert dashboard["saved_searches"][0]["is_default"] is True
    assert dashboard["saved_searches"][0]["search_preferences"]["target_titles"] == [
        "Support Engineering Manager"
    ]


def test_saved_search_run_queues_and_processes_background_discovery(client, monkeypatch):
    seed_profile(client)
    dashboard_response = client.get("/api/dashboard")
    saved_search_id = dashboard_response.json()["saved_searches"][0]["id"]

    monkeypatch.setattr(
        "apps.api.app.services.background_tasks.discover_jobs_from_web",
        lambda **_kwargs: WebDiscoveryResult(
            jobs=[
                {
                    "source": "greenhouse",
                    "external_id": "platform-upgrade-queued-1",
                    "company": "Anthropic",
                    "title": "Support Engineering Manager",
                    "location": "London, UK",
                    "employment_type": "Full-time",
                    "url": "https://boards.greenhouse.io/example-company/jobs/platform-upgrade-queued-1",
                    "description": "Lead support engineering teams for AI infrastructure.",
                    "requirements": ["Python", "incident management"],
                    "metadata_json": {"discovery": {"why_match": "Support leadership overlap."}},
                    "discovery_method": "gemini_grounded_search",
                    "status": "discovered",
                }
            ],
            search_queries=["support engineering manager london greenhouse"],
            source_urls=["https://boards.greenhouse.io/example-company/jobs/platform-upgrade-queued-1"],
            grounded_pages_count=1,
            diagnostics={"candidate_count": 1, "accepted_job_count": 1, "rejected_pages_count": 0},
        ),
    )

    queue_response = client.post(f"/api/searches/{saved_search_id}/run")
    assert queue_response.status_code == 200
    assert queue_response.json()["status"] == "queued"

    process_response = client.post("/api/tasks/process?limit=1")
    assert process_response.status_code == 200
    assert process_response.json()["processed"] == 1

    refreshed_dashboard = client.get("/api/dashboard")
    assert refreshed_dashboard.status_code == 200
    dashboard = refreshed_dashboard.json()

    assert len(dashboard["jobs"]) == 1
    assert dashboard["jobs"][0]["discovery_method"] == "gemini_grounded_search"
    assert dashboard["background_tasks"][0]["status"] == "succeeded"
    assert dashboard["discovery_runs"][0]["status"] == "completed"
    assert dashboard["saved_search_matches"][0]["saved_search_id"] == saved_search_id

    with SessionLocal() as session:
        task = session.execute(select(BackgroundTask)).scalar_one()
        run = session.execute(select(DiscoveryRun)).scalar_one()
        match = session.execute(select(SavedSearchMatch)).scalar_one()
        assert task.status == "succeeded"
        assert run.jobs_created_count == 1
        assert match.current_score is not None


def test_queue_worker_run_processes_placeholder_result(client, monkeypatch):
    seed_profile(client)
    job_id = create_job(client)
    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft_id = draft_response.json()["id"]

    monkeypatch.setattr(
        "apps.api.app.services.background_tasks.run_worker",
        lambda _request: {
            "application_draft_id": draft_id,
            "platform": "greenhouse",
            "target_url": "https://boards.greenhouse.io/example-company/jobs/platform-upgrade-1",
            "dry_run": True,
            "status": "preview_ready",
            "actions": [],
            "logs": ["Queued worker preview finished."],
            "screenshot_path": None,
            "fields": [],
            "review_items": [],
            "preview_summary": {
                "total_fields": 0,
                "autofill_ready_count": 0,
                "required_count": 0,
                "review_required_count": 0,
                "unresolved_required_count": 0,
                "llm_suggestions_count": 0,
            },
            "profile_snapshot": {},
            "job_snapshot": {},
            "draft_snapshot": {},
        },
    )

    queue_response = client.post(
        f"/api/applications/{draft_id}/queue-run",
        json={"dry_run": True, "confirm_submit": False},
    )
    assert queue_response.status_code == 200
    assert queue_response.json()["status"] == "queued"

    dashboard_before = client.get("/api/dashboard").json()
    assert dashboard_before["worker_runs"][0]["status"] == "queued"

    process_response = client.post("/api/tasks/process?limit=1")
    assert process_response.status_code == 200
    assert process_response.json()["processed"] == 1

    dashboard_after = client.get("/api/dashboard").json()
    assert dashboard_after["worker_runs"][0]["status"] == "preview_ready"
    assert dashboard_after["background_tasks"][0]["status"] == "succeeded"

    with SessionLocal() as session:
        worker_run = session.execute(select(WorkerRun)).scalar_one()
        assert worker_run.status == "preview_ready"


def test_queue_worker_run_reuses_existing_active_task(client):
    seed_profile(client)
    job_id = create_job(client)
    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft_id = draft_response.json()["id"]

    first_response = client.post(
        f"/api/applications/{draft_id}/queue-run",
        json={"dry_run": True, "confirm_submit": False},
    )
    assert first_response.status_code == 200

    second_response = client.post(
        f"/api/applications/{draft_id}/queue-run",
        json={"dry_run": True, "confirm_submit": False},
    )
    assert second_response.status_code == 200
    assert second_response.json()["id"] == first_response.json()["id"]
    assert second_response.json()["worker_run_id"] == first_response.json()["worker_run_id"]

    with SessionLocal() as session:
        task_count = session.execute(
            select(BackgroundTask).where(BackgroundTask.application_draft_id == draft_id)
        ).scalars().all()
        worker_run_count = session.execute(
            select(WorkerRun).where(WorkerRun.application_draft_id == draft_id)
        ).scalars().all()
        assert len(task_count) == 1
        assert len(worker_run_count) == 1


def test_application_submit_routes_block_duplicate_submission(client):
    seed_profile(client)
    job_id = create_job(client)
    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft_id = draft_response.json()["id"]

    with SessionLocal() as session:
        draft = session.execute(
            select(ApplicationDraft).where(ApplicationDraft.id == draft_id)
        ).scalar_one()
        draft.status = "submitted"
        draft.job_lead.status = "submitted"
        session.commit()

    queue_response = client.post(
        f"/api/applications/{draft_id}/queue-run",
        json={"dry_run": False, "confirm_submit": True},
    )
    assert queue_response.status_code == 409
    assert "retry_anyway" in queue_response.json()["detail"]

    run_response = client.post(
        f"/api/applications/{draft_id}/run",
        json={"dry_run": False, "confirm_submit": True},
    )
    assert run_response.status_code == 409
    assert "retry_anyway" in run_response.json()["detail"]

    with SessionLocal() as session:
        task_count = session.execute(
            select(BackgroundTask).where(BackgroundTask.application_draft_id == draft_id)
        ).scalars().all()
        worker_run_count = session.execute(
            select(WorkerRun).where(WorkerRun.application_draft_id == draft_id)
        ).scalars().all()
        assert task_count == []
        assert worker_run_count == []


def test_application_submit_retry_anyway_bypasses_duplicate_block(client):
    seed_profile(client)
    job_id = create_job(client)
    draft_response = client.post(f"/api/jobs/{job_id}/draft")
    assert draft_response.status_code == 200
    draft_id = draft_response.json()["id"]

    with SessionLocal() as session:
        draft = session.execute(
            select(ApplicationDraft).where(ApplicationDraft.id == draft_id)
        ).scalar_one()
        draft.status = "submit_clicked"
        draft.job_lead.status = "submit_clicked"
        session.commit()

    queue_response = client.post(
        f"/api/applications/{draft_id}/queue-run",
        json={"dry_run": False, "confirm_submit": True, "retry_anyway": True},
    )
    assert queue_response.status_code == 200
    assert queue_response.json()["status"] == "queued"

    with SessionLocal() as session:
        task_count = session.execute(
            select(BackgroundTask).where(BackgroundTask.application_draft_id == draft_id)
        ).scalars().all()
        worker_run_count = session.execute(
            select(WorkerRun).where(WorkerRun.application_draft_id == draft_id)
        ).scalars().all()
        assert len(task_count) == 1
        assert len(worker_run_count) == 1


def test_job_crm_patch_updates_role_state(client):
    seed_profile(client)
    job_id = create_job(client)

    response = client.patch(
        f"/api/jobs/{job_id}/crm",
        json={
            "crm_stage": "interviewing",
            "crm_notes": "Recruiter screen scheduled.",
            "is_active": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["crm_stage"] == "interviewing"
    assert payload["crm_notes"] == "Recruiter screen scheduled."
    assert payload["is_active"] is True


def test_worker_health_endpoint_reports_ready_state(client, monkeypatch):
    monkeypatch.setattr(
        "apps.api.app.services.health._check_chromium_install",
        lambda: ("/tmp/chromium", True),
    )

    response = client.get("/api/health/worker")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert payload["checks"]["database_ok"] is True
    assert payload["checks"]["chromium_installed"] is True


def test_migrate_database_upgrades_legacy_sqlite_schema(tmp_path, monkeypatch):
    legacy_path = Path(tmp_path) / "legacy.db"
    legacy_engine = create_engine(
        f"sqlite:///{legacy_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE candidate_profiles (
              id INTEGER PRIMARY KEY,
              full_name VARCHAR(255),
              headline VARCHAR(255),
              email VARCHAR(255),
              phone VARCHAR(64),
              location VARCHAR(255),
              source_of_truth VARCHAR(32) NOT NULL DEFAULT 'cv',
              raw_cv_text TEXT,
              merged_profile JSON NOT NULL DEFAULT '{}',
              field_sources JSON NOT NULL DEFAULT '{}',
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE profile_sources (
              id INTEGER PRIMARY KEY,
              profile_id INTEGER,
              source_type VARCHAR(32),
              source_label VARCHAR(255),
              raw_text TEXT,
              parsed_payload JSON NOT NULL DEFAULT '{}',
              confidence JSON NOT NULL DEFAULT '{}',
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE job_leads (
              id INTEGER PRIMARY KEY,
              source VARCHAR(32),
              external_id VARCHAR(255),
              company VARCHAR(255),
              title VARCHAR(255),
              location VARCHAR(255),
              employment_type VARCHAR(128),
              url VARCHAR(1024),
              description TEXT,
              requirements JSON NOT NULL DEFAULT '[]',
              metadata_json JSON NOT NULL DEFAULT '{}',
              score FLOAT,
              score_details JSON NOT NULL DEFAULT '{}',
              research JSON NOT NULL DEFAULT '{}',
              status VARCHAR(32) NOT NULL DEFAULT 'discovered',
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO job_leads (
              id, source, external_id, company, title, location, employment_type, url,
              description, requirements, metadata_json, score, score_details, research,
              status, created_at, updated_at
            ) VALUES (
              1, 'greenhouse', 'legacy-1', 'Legacy Co', 'Legacy Role', 'London, UK', 'Full-time',
              'https://example.com/jobs/legacy-1', 'Legacy description', '[]', '{}', NULL, '{}', '{}',
              'submit_clicked', '2026-03-10 09:00:00', '2026-03-10 10:00:00'
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE application_drafts (
              id INTEGER PRIMARY KEY,
              profile_id INTEGER,
              job_lead_id INTEGER,
              tailored_summary TEXT,
              cover_note TEXT,
              resume_bullets JSON NOT NULL DEFAULT '[]',
              screening_answers JSON NOT NULL DEFAULT '[]',
              status VARCHAR(32) NOT NULL DEFAULT 'drafted',
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE worker_runs (
              id INTEGER PRIMARY KEY,
              application_draft_id INTEGER,
              platform VARCHAR(32),
              target_url VARCHAR(1024),
              dry_run BOOLEAN NOT NULL DEFAULT 1,
              status VARCHAR(32) NOT NULL DEFAULT 'planned',
              actions JSON NOT NULL DEFAULT '[]',
              logs JSON NOT NULL DEFAULT '[]',
              screenshot_path VARCHAR(1024),
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO application_drafts (
              id, profile_id, job_lead_id, tailored_summary, cover_note, resume_bullets,
              screening_answers, status, created_at, updated_at
            ) VALUES (
              1, 1, 1, 'Legacy summary', 'Legacy cover note', '[]', '[]',
              'submit_clicked', '2026-03-10 09:00:00', '2026-03-10 10:00:00'
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO worker_runs (
              id, application_draft_id, platform, target_url, dry_run, status, actions, logs,
              screenshot_path, created_at
            ) VALUES (
              1, 1, 'greenhouse', 'https://example.com/jobs/legacy-1', 0, 'submit_clicked', '[]',
              '["Clicked submit using button[type=''submit''].", "Submit was clicked, but the form still appears invalid; ATS confirmation was not detected."]',
              NULL, '2026-03-10 10:00:00'
            )
            """
        )

    monkeypatch.setattr(db_module, "engine", legacy_engine)
    monkeypatch.setattr(
        db_module,
        "SessionLocal",
        sessionmaker(bind=legacy_engine, autoflush=False, autocommit=False, future=True),
    )

    db_module.migrate_database()
    inspector = inspect(legacy_engine)

    assert "schema_migrations" in inspector.get_table_names()
    assert "saved_searches" in inspector.get_table_names()
    assert "background_tasks" in inspector.get_table_names()
    assert {
        "search_preferences",
        "search_preferences_customized",
    }.issubset({column["name"] for column in inspector.get_columns("candidate_profiles")})
    assert {"discovery_method", "crm_stage", "is_active"}.issubset(
        {column["name"] for column in inspector.get_columns("job_leads")}
    )

    with legacy_engine.begin() as connection:
        upgraded_row = connection.exec_driver_sql(
            """
            SELECT discovery_method, crm_stage, is_active, first_seen_at, last_seen_at, last_checked_at, status
            FROM job_leads
            WHERE id = 1
            """
        ).one()
        upgraded_draft_row = connection.exec_driver_sql(
            """
            SELECT status
            FROM application_drafts
            WHERE id = 1
            """
        ).one()
        upgraded_worker_run_row = connection.exec_driver_sql(
            """
            SELECT status
            FROM worker_runs
            WHERE id = 1
            """
        ).one()
        applied_versions = connection.exec_driver_sql(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert upgraded_row[0] == "direct"
    assert upgraded_row[1] == "new"
    assert upgraded_row[2] == 1
    assert upgraded_row[3] is not None
    assert upgraded_row[4] is not None
    assert upgraded_row[5] is not None
    assert upgraded_row[6] == "submit_failed"
    assert upgraded_draft_row[0] == "submit_failed"
    assert upgraded_worker_run_row[0] == "submit_failed"
    assert applied_versions == [(1,), (2,)]
