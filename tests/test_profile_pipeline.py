from __future__ import annotations


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
