from __future__ import annotations

from apps.api.app.schemas import CandidateProfilePayload, ExperienceItem
from apps.api.app.services.job_sources.greenhouse import normalize_greenhouse_job
from apps.api.app.services.job_sources.lever import normalize_lever_job
from apps.api.app.services.matching import rank_job


def test_greenhouse_normalization_extracts_core_fields():
    normalized = normalize_greenhouse_job(
        "example-company",
        {
            "id": 42,
            "title": "Senior ML Engineer",
            "location": {"name": "Remote"},
            "absolute_url": "https://boards.greenhouse.io/example-company/jobs/42",
            "content": "<p>Build ML systems with Python and FastAPI.</p>",
            "questions": [{"label": "Do you need visa sponsorship?"}],
            "metadata": [{"name": "Employment Type", "value": "Full-time"}],
            "departments": [{"name": "Engineering"}],
            "offices": [{"name": "Remote"}],
        },
    )
    assert normalized["source"] == "greenhouse"
    assert normalized["company"] == "Example Company"
    assert "Python" in normalized["description"]
    assert normalized["requirements"] == []
    assert normalized["metadata_json"]["application_questions"]["questions"] == [
        {"label": "Do you need visa sponsorship?"}
    ]


def test_lever_normalization_extracts_categories():
    normalized = normalize_lever_job(
        "example-company",
        {
            "id": "abc123",
            "text": "Platform Engineer",
            "hostedUrl": "https://jobs.lever.co/example-company/abc123",
            "description": "<p>Operate backend services with Docker and Kubernetes.</p>",
            "lists": [{"text": "Requirements", "content": "<ul><li>Python</li><li>AWS</li></ul>"}],
            "categories": {
                "team": "Infrastructure",
                "commitment": "Full-time",
                "location": "Paris",
            },
            "workplaceType": "remote",
        },
    )
    assert normalized["source"] == "lever"
    assert normalized["employment_type"] == "Full-time"
    assert "AWS" in normalized["description"]


def test_rank_job_scores_matching_profile():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        headline="Senior AI Engineer",
        summary="Python engineer shipping LLM and automation systems.",
        skills=["Python", "FastAPI", "LLM", "React"],
        achievements=[],
        experiences=[
            ExperienceItem(company="Acme", title="Senior AI Engineer", highlights=[])
        ],
        education=[],
        links={},
    )
    ranking = rank_job(
        profile,
        {
            "title": "AI Engineer",
            "description": "Build Python and LLM services with FastAPI.",
            "requirements": ["React"],
            "metadata_json": {},
            "location": "Remote",
        },
    )
    assert ranking.score >= 60
    assert "Python" in ranking.matched_skills


def test_rank_job_penalizes_us_roles_for_london_profile():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        headline="Senior AI Engineer",
        location="London, United Kingdom",
        summary="Python engineer shipping LLM and automation systems.",
        skills=["Python", "FastAPI", "LLM"],
        achievements=[],
        experiences=[
            ExperienceItem(company="Acme", title="Senior AI Engineer", highlights=[])
        ],
        education=[],
        links={},
    )

    london_role = rank_job(
        profile,
        {
            "title": "Senior AI Engineer",
            "description": "Build Python and LLM systems for applied AI products.",
            "requirements": ["FastAPI"],
            "metadata_json": {"workplaceType": "remote"},
            "location": "London, United Kingdom",
        },
    )
    us_role = rank_job(
        profile,
        {
            "title": "Senior AI Engineer",
            "description": "Build Python and LLM systems for applied AI products.",
            "requirements": ["FastAPI"],
            "metadata_json": {"workplaceType": "remote"},
            "location": "Remote - United States",
        },
    )

    assert london_role.score > us_role.score
    assert us_role.score <= 40
    assert any("restricted" in signal for signal in us_role.missing_signals)


def test_rank_job_prefers_title_alignment_over_skill_overlap():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        headline="Senior Product Manager",
        location="London, United Kingdom",
        summary="Product leader working across roadmap, experimentation, and analytics.",
        skills=["Python", "SQL", "Analytics"],
        achievements=[],
        experiences=[
            ExperienceItem(company="Acme", title="Product Manager", highlights=[]),
            ExperienceItem(company="Beta", title="Senior Product Manager", highlights=[]),
        ],
        education=[],
        links={},
    )

    product_role = rank_job(
        profile,
        {
            "title": "Senior Product Manager",
            "description": "Own product strategy, roadmap, and experimentation.",
            "requirements": ["Analytics", "SQL"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )
    technical_role = rank_job(
        profile,
        {
            "title": "Machine Learning Engineer",
            "description": "Build Python services, pipelines, and experimentation tooling.",
            "requirements": ["Python", "SQL"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )

    assert product_role.score > technical_role.score
    assert technical_role.score <= 55
    assert "recent roles" in technical_role.summary or technical_role.score < 50


def test_rank_job_prefers_support_titles_over_research_titles():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        headline="ML Support Engineering Leader",
        location="London, United Kingdom",
        summary="Support engineering leader for AI products and customer escalations.",
        skills=["Python", "SQL", "AWS", "Kubernetes"],
        achievements=[],
        experiences=[
            ExperienceItem(company="Acme", title="ML Support Engineer", highlights=[]),
            ExperienceItem(company="Acme", title="Customer Support Engineer", highlights=[]),
        ],
        education=[],
        links={},
    )

    support_role = rank_job(
        profile,
        {
            "title": "Product Support Specialist",
            "description": "Help customers unblock Python and AWS workflows in production.",
            "requirements": ["SQL"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )
    research_role = rank_job(
        profile,
        {
            "title": "Research Engineer, Machine Learning",
            "description": "Build reinforcement learning systems with Python and Kubernetes.",
            "requirements": ["AWS"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )

    assert support_role.score > research_role.score
    assert "research" in " ".join(research_role.missing_signals).lower()


def test_rank_job_prefers_management_scope_for_manager_profile():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        headline="ML Support Engineering Leader",
        location="London, United Kingdom",
        summary=(
            "Scaled ML support from individual contributor to department head, "
            "building and managing global teams."
        ),
        skills=["Python", "SQL", "AWS"],
        achievements=[],
        experiences=[],
        education=[],
        links={},
    )

    manager_role = rank_job(
        profile,
        {
            "title": "Support Operations Manager",
            "description": "Manage support delivery, escalations, and Python-based workflows.",
            "requirements": ["SQL"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )
    ic_role = rank_job(
        profile,
        {
            "title": "Product Support Specialist",
            "description": "Handle support escalations and troubleshoot Python workflows.",
            "requirements": ["SQL"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )

    assert manager_role.score > ic_role.score
    assert any("individual contributor" in signal for signal in ic_role.missing_signals)


def test_rank_job_penalizes_manager_scope_for_ic_profile():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        headline="Customer Support Engineer",
        location="London, United Kingdom",
        summary="Hands-on support engineer resolving customer escalations.",
        skills=["Python", "SQL", "AWS"],
        achievements=[],
        experiences=[
            ExperienceItem(company="Acme", title="Senior Support Engineer", highlights=[])
        ],
        education=[],
        links={},
    )

    ic_role = rank_job(
        profile,
        {
            "title": "Senior Support Engineer",
            "description": "Troubleshoot customer issues with Python and AWS.",
            "requirements": ["SQL"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )
    manager_role = rank_job(
        profile,
        {
            "title": "Support Operations Manager",
            "description": "Manage support delivery, escalations, and coaching.",
            "requirements": ["SQL"],
            "metadata_json": {},
            "location": "London, United Kingdom",
        },
    )

    assert ic_role.score > manager_role.score
    assert any("people management" in signal for signal in manager_role.missing_signals)
