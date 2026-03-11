from __future__ import annotations

from pathlib import Path


def test_cv_and_linkedin_merge_into_profile(client):
    cv_text = """
    Paul Example
    AI Product Engineer
    paul@example.com
    Paris, France

    Summary
    Builder focused on AI products, automation, and applied machine learning.

    Skills
    Python, FastAPI, SQL, React

    Experience
    Acme AI | Senior Engineer | 2022 - Present
    - Built production LLM workflows for internal teams
    - Automated reporting pipelines with Python and SQL
    """.strip()

    response = client.post(
        "/api/profile/cv",
        files={"file": ("resume.txt", cv_text.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 200
    profile = response.json()
    assert profile["full_name"] == "Paul Example"
    assert "Python" in profile["merged_profile"]["skills"]
    assert profile["merged_profile"]["links"]["resume_path"].endswith("latest_resume.txt")
    assert "AI Product Engineer" in profile["search_preferences"]["target_titles"]
    assert "Python" in profile["search_preferences"]["include_keywords"]

    linkedin_text = """
    Paul Example
    Staff AI Engineer
    About
    Shipping AI systems for workflow acceleration.

    Skills
    Python
    LLM
    Playwright
    """.strip()
    linkedin_response = client.post("/api/profile/linkedin", data={"text": linkedin_text})
    assert linkedin_response.status_code == 200
    merged_profile = linkedin_response.json()
    assert "LLM" in merged_profile["merged_profile"]["skills"]
    assert merged_profile["field_sources"]["skills"] == "cv+linkedin"

    dashboard_response = client.get("/api/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert len(dashboard["profile_sources"]) == 2
    assert dashboard["profile"]["search_preferences"]["target_titles"]
    assert "Paris, France" in dashboard["profile"]["search_preferences"]["locations"]


def test_delete_cv_source_removes_resume_and_keeps_remaining_linkedin_profile(client):
    cv_text = """
    Paul Example
    AI Product Engineer
    paul@example.com
    Paris, France

    Summary
    Builder focused on AI products, automation, and applied machine learning.

    Skills
    Python, FastAPI, SQL, React
    """.strip()

    cv_response = client.post(
        "/api/profile/cv",
        files={"file": ("resume.txt", cv_text.encode("utf-8"), "text/plain")},
    )
    assert cv_response.status_code == 200
    resume_path = Path(cv_response.json()["merged_profile"]["links"]["resume_path"])
    assert resume_path.exists()

    linkedin_text = """
    Paul Example
    Staff AI Engineer
    About
    Shipping AI systems for workflow acceleration.

    Skills
    Python
    LLM
    Playwright
    """.strip()
    linkedin_response = client.post("/api/profile/linkedin", data={"text": linkedin_text})
    assert linkedin_response.status_code == 200

    dashboard_response = client.get("/api/dashboard")
    source_id = next(
        source["id"]
        for source in dashboard_response.json()["profile_sources"]
        if source["source_type"] == "cv"
    )

    delete_response = client.delete(f"/api/profile/sources/{source_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["entity"] == "profile_source"
    assert resume_path.exists() is False

    refreshed_dashboard = client.get("/api/dashboard")
    assert refreshed_dashboard.status_code == 200
    dashboard = refreshed_dashboard.json()

    assert len(dashboard["profile_sources"]) == 1
    assert dashboard["profile_sources"][0]["source_type"] == "linkedin"
    assert "resume_path" not in dashboard["profile"]["merged_profile"]["links"]
    assert "LLM" in dashboard["profile"]["merged_profile"]["skills"]
    assert "React" not in dashboard["profile"]["merged_profile"]["skills"]


def test_manual_profile_update_reranks_existing_jobs(client):
    initial_profile = {
        "full_name": "Paul Example",
        "headline": "ML Support Engineering Leader",
        "email": "paul@example.com",
        "phone": None,
        "location": "London, UK",
        "summary": "Support engineering leader for AI products.",
        "skills": ["Python", "SQL", "AWS"],
        "achievements": [],
        "experiences": [],
        "education": [],
        "links": {},
    }
    response = client.put("/api/profile", json=initial_profile)
    assert response.status_code == 200

    lead_response = client.post(
        "/api/jobs/discover/linkedin",
        json={
            "company": "Anthropic",
            "title": "Product Support Specialist",
            "url": "https://example.com/jobs/support",
            "location": "London, UK",
            "description": "Support AI customers with Python, SQL, AWS, and LLM workflows.",
            "notes": None,
        },
    )
    assert lead_response.status_code == 200
    initial_score = lead_response.json()["score"]

    updated_profile = dict(initial_profile)
    updated_profile["headline"] = "Software Engineer"
    updated_profile["summary"] = "Backend engineer focused on internal platforms."
    rerank_response = client.put("/api/profile", json=updated_profile)
    assert rerank_response.status_code == 200

    jobs_response = client.get("/api/jobs")
    assert jobs_response.status_code == 200
    reranked_job = jobs_response.json()[0]

    assert reranked_job["title"] == "Product Support Specialist"
    assert reranked_job["score"] < initial_score


def test_manual_profile_update_persists_custom_search_preferences(client):
    initial_profile = {
        "full_name": "Paul Example",
        "headline": "ML Support Engineering Leader",
        "email": "paul@example.com",
        "phone": None,
        "location": "London, UK",
        "summary": "Support engineering leader for AI products.",
        "skills": ["Python", "SQL", "AWS"],
        "achievements": [],
        "experiences": [],
        "education": [],
        "links": {},
        "search_preferences": {
            "target_titles": ["AI Support Engineer", "Customer Engineer"],
            "target_responsibilities": ["Lead high-severity customer escalations"],
            "locations": ["London, UK"],
            "workplace_modes": ["hybrid"],
            "include_keywords": ["Python", "incident management"],
            "exclude_keywords": ["sales"],
            "companies_include": ["Anthropic"],
            "companies_exclude": ["Meta"],
            "result_limit": 7,
        },
    }

    response = client.put("/api/profile", json=initial_profile)
    assert response.status_code == 200
    profile = response.json()
    assert profile["search_preferences"]["target_titles"] == [
        "AI Support Engineer",
        "Customer Engineer",
    ]
    assert profile["search_preferences"]["exclude_keywords"] == ["sales"]

    follow_up_response = client.put(
        "/api/profile",
        json={
            **initial_profile,
            "headline": "Principal Support Engineer",
            "summary": "Support engineering leader focused on AI infrastructure.",
        },
    )
    assert follow_up_response.status_code == 200
    follow_up_profile = follow_up_response.json()
    assert follow_up_profile["search_preferences"]["target_titles"] == [
        "AI Support Engineer",
        "Customer Engineer",
    ]
    assert follow_up_profile["search_preferences"]["result_limit"] == 7
