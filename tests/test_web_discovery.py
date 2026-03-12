from __future__ import annotations

import sys
import types as py_types

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from apps.api.app.config import settings
from apps.api.app.db import SessionLocal
from apps.api.app.models import JobLead
from apps.api.app.routers import jobs as jobs_router
from apps.api.app.schemas import CandidateProfilePayload, SearchPreferencesPayload
from apps.api.app.services.job_discovery.service import (
    FetchedJobPage,
    GeminiGroundedSearchClient,
    GroundedJobCandidate,
    GroundedSearchResult,
    RetryableWebDiscoveryError,
    WebDiscoveryError,
    WebDiscoveryResult,
    _extract_supported_apply_links,
    discover_jobs_from_web,
)


def test_gemini_grounded_search_client_parses_candidates_and_metadata(monkeypatch):
    class FakeGroundingMetadata:
        def __init__(self):
            self.web_search_queries = ["ai support engineer london", "python customer support ai"]
            self.grounding_chunks = [
                {"web": {"uri": "https://boards.greenhouse.io/example/jobs/123", "title": "Example"}},
                {"web": {"uri": "https://jobs.example.com/ai-support-engineer", "title": "Jobs"}},
            ]

    class FakeCandidate:
        def __init__(self):
            self.grounding_metadata = FakeGroundingMetadata()

    class FakeResponse:
        text = """
        {
          "candidates": [
            {
              "company": "Example",
              "title": "AI Support Engineer",
              "url": "https://boards.greenhouse.io/example/jobs/123",
              "location": "London, UK",
              "employment_type": "Full-time",
              "source_hint": "greenhouse",
              "description_snippet": "Support AI customers with Python.",
              "why_match": "Strong overlap with AI support leadership."
            }
          ]
        }
        """
        candidates = [FakeCandidate()]

    class FakeModels:
        def generate_content(self, **_kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = FakeModels()

    class FakeTool:
        def __init__(self, **_kwargs):
            pass

    class FakeGoogleSearch:
        pass

    class FakeGenerateContentConfig:
        def __init__(self, **_kwargs):
            pass

    fake_genai_module = py_types.ModuleType("google.genai")
    fake_genai_module.Client = FakeClient
    fake_types_module = py_types.SimpleNamespace(
        Tool=FakeTool,
        GoogleSearch=FakeGoogleSearch,
        GenerateContentConfig=FakeGenerateContentConfig,
    )
    fake_genai_module.types = fake_types_module

    fake_google_module = py_types.ModuleType("google")
    fake_google_module.genai = fake_genai_module

    monkeypatch.setitem(sys.modules, "google", fake_google_module)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai_module)

    client = GeminiGroundedSearchClient(
        api_key="test-key",
        model="gemini-3-flash-preview",
        timeout_seconds=10,
    )
    result = client.search_jobs(
        profile=CandidateProfilePayload(
            headline="AI Support Engineer",
            summary="Support leader for AI products.",
            location="London, UK",
            skills=["Python", "Support"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["AI Support Engineer"],
            target_responsibilities=["Lead customer escalations"],
            locations=["London, UK"],
            workplace_modes=["hybrid"],
            include_keywords=["Python"],
            exclude_keywords=[],
            companies_include=[],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert result.candidates[0].title == "AI Support Engineer"
    assert result.candidates[0].source_hint == "greenhouse"
    assert result.search_queries == ["ai support engineer london", "python customer support ai"]
    assert "https://boards.greenhouse.io/example/jobs/123" in result.source_urls


def test_gemini_grounded_search_client_falls_back_to_candidate_parts_when_text_missing(monkeypatch):
    class FakeGroundingMetadata:
        def __init__(self):
            self.web_search_queries = ["support engineer london"]
            self.grounding_chunks = [
                {"web": {"uri": "https://boards.greenhouse.io/example/jobs/123", "title": "Example"}}
            ]

    class FakePart:
        def __init__(self, text: str):
            self.text = text

    class FakeContent:
        def __init__(self):
            self.parts = [
                FakePart(
                    """
                    {
                      "candidates": [
                        {
                          "company": "Example",
                          "title": "Support Engineer",
                          "url": "https://boards.greenhouse.io/example/jobs/123",
                          "location": "London, UK",
                          "employment_type": "Full-time",
                          "source_hint": "greenhouse",
                          "description_snippet": "Support production systems.",
                          "why_match": "Support background."
                        }
                      ]
                    }
                    """
                )
            ]

    class FakeCandidate:
        def __init__(self):
            self.grounding_metadata = FakeGroundingMetadata()
            self.content = FakeContent()

    class FakeResponse:
        text = None
        candidates = [FakeCandidate()]

    class FakeModels:
        def generate_content(self, **_kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = FakeModels()

    class FakeTool:
        def __init__(self, **_kwargs):
            pass

    class FakeGoogleSearch:
        pass

    class FakeGenerateContentConfig:
        def __init__(self, **_kwargs):
            pass

    fake_genai_module = py_types.ModuleType("google.genai")
    fake_genai_module.Client = FakeClient
    fake_types_module = py_types.SimpleNamespace(
        Tool=FakeTool,
        GoogleSearch=FakeGoogleSearch,
        GenerateContentConfig=FakeGenerateContentConfig,
    )
    fake_genai_module.types = fake_types_module

    fake_google_module = py_types.ModuleType("google")
    fake_google_module.genai = fake_genai_module

    monkeypatch.setitem(sys.modules, "google", fake_google_module)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai_module)

    client = GeminiGroundedSearchClient(
        api_key="test-key",
        model="gemini-3.1-pro-preview",
        timeout_seconds=10,
    )
    result = client.search_jobs(
        profile=CandidateProfilePayload(
            headline="Support Engineer",
            summary="Production support engineer.",
            location="London, UK",
            skills=["Support"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["Support Engineer"],
            target_responsibilities=["Handle escalations"],
            locations=["London, UK"],
            workplace_modes=["hybrid"],
            include_keywords=["Support"],
            exclude_keywords=[],
            companies_include=[],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert result.candidates[0].title == "Support Engineer"
    assert result.search_queries == ["support engineer london"]
    assert result.source_urls == ["https://boards.greenhouse.io/example/jobs/123"]


def test_extract_supported_apply_links_uses_page_context_for_generic_apply_links():
    soup = BeautifulSoup(
        """
        <html>
          <head>
            <title>Senior Manager, Support Engineering - Europe | Sanity</title>
          </head>
          <body>
            <h1>Senior Manager, Support Engineering - Europe</h1>
            <a href="https://jobs.ashbyhq.com/sanity/ec701d24-cda8-47f4-a58c-a89747f4da23/application">
              Apply for this position
            </a>
          </body>
        </html>
        """,
        "html.parser",
    )

    assert _extract_supported_apply_links(
        soup,
        base_url="https://www.sanity.io/careers/senior-manager-support-engineering-europe",
        page_title="Senior Manager, Support Engineering - Europe | Sanity",
        heading="Senior Manager, Support Engineering - Europe",
    ) == [
        (
            "https://jobs.ashbyhq.com/sanity/ec701d24-cda8-47f4-a58c-a89747f4da23",
            "Senior Manager, Support Engineering - Europe",
        )
    ]


def test_discover_jobs_from_web_retries_transient_gemini_failures(monkeypatch):
    attempts = {"count": 0}
    monkeypatch.setattr(settings, "gemini_discovery_max_attempts", 2)

    def fake_search_jobs(self, *, profile, search_preferences):
        attempts["count"] += 1
        assert profile.headline == "AI Support Engineer"
        assert search_preferences.target_titles == ["AI Support Engineer"]
        if attempts["count"] == 1:
            raise RetryableWebDiscoveryError(
                "Gemini grounded search did not return any structured job candidates."
            )
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Example",
                    title="AI Support Engineer",
                    url="https://boards.greenhouse.io/example/jobs/123",
                    location="London, UK",
                    employment_type="Full-time",
                    source_hint="greenhouse",
                    description_snippet="Support AI customers with Python and SQL.",
                    why_match="Matches the support-intent profile.",
                )
            ],
            search_queries=["ai support engineer london"],
            source_urls=["https://boards.greenhouse.io/example/jobs/123"],
        )

    def fake_fetch_job_page(_url: str):
        return FetchedJobPage(
            final_url="https://boards.greenhouse.io/example/jobs/123",
            canonical_url="https://boards.greenhouse.io/example/jobs/123",
            page_title="Example - AI Support Engineer",
            heading="AI Support Engineer",
            company="Example",
            location="London, UK",
            employment_type="Full-time",
            description="Support AI customers with Python and SQL in production.",
            requirements=["3+ years supporting AI systems"],
        )

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)

    result = discover_jobs_from_web(
        profile=CandidateProfilePayload(
            headline="AI Support Engineer",
            summary="Support leader for AI products.",
            location="London, UK",
            skills=["Python", "SQL"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["AI Support Engineer"],
            target_responsibilities=["Lead customer escalations"],
            locations=["London, UK"],
            workplace_modes=["hybrid"],
            include_keywords=["Python"],
            exclude_keywords=[],
            companies_include=[],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert attempts["count"] == 2
    assert len(result.jobs) == 1
    assert result.jobs[0]["source"] == "greenhouse"


def test_discover_jobs_from_web_reports_retry_exhaustion(monkeypatch):
    attempts = {"count": 0}
    monkeypatch.setattr(settings, "gemini_discovery_max_attempts", 2)

    def fake_search_jobs(self, *, profile, search_preferences):
        attempts["count"] += 1
        assert profile.headline == "AI Support Engineer"
        assert search_preferences.target_titles == ["AI Support Engineer"]
        raise RetryableWebDiscoveryError(
            "Gemini grounded search did not return any structured job candidates."
        )

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)

    with pytest.raises(
        WebDiscoveryError,
        match="AI web discovery failed after 2 Gemini attempts",
    ):
        discover_jobs_from_web(
            profile=CandidateProfilePayload(
                headline="AI Support Engineer",
                summary="Support leader for AI products.",
                location="London, UK",
                skills=["Python", "SQL"],
                achievements=[],
                experiences=[],
                education=[],
                links={},
            ),
            search_preferences=SearchPreferencesPayload(
                target_titles=["AI Support Engineer"],
                target_responsibilities=["Lead customer escalations"],
                locations=["London, UK"],
                workplace_modes=["hybrid"],
                include_keywords=["Python"],
                exclude_keywords=[],
                companies_include=[],
                companies_exclude=[],
                result_limit=5,
            ),
        )

    assert attempts["count"] == 2


def test_discover_jobs_from_web_normalizes_grounded_candidates(monkeypatch):
    def fake_search_jobs(self, *, profile, search_preferences):
        assert profile.headline == "AI Support Engineer"
        assert search_preferences.target_titles == ["AI Support Engineer"]
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Example",
                    title="AI Support Engineer",
                    url="https://boards.greenhouse.io/example/jobs/123?gh_jid=123",
                    location="London, UK",
                    employment_type="Full-time",
                    source_hint="greenhouse",
                    description_snippet="Support AI customers with Python and SQL.",
                    why_match="Matches the support-intent profile.",
                )
            ],
            search_queries=["ai support engineer london"],
            source_urls=["https://boards.greenhouse.io/example/jobs/123"],
        )

    def fake_fetch_job_page(_url: str):
        return FetchedJobPage(
            final_url="https://boards.greenhouse.io/example/jobs/123",
            page_title="Example - AI Support Engineer",
            heading="AI Support Engineer",
            company="Example",
            location="London, UK",
            employment_type="Full-time",
            description="Support AI customers with Python and SQL in production.",
            requirements=["3+ years supporting AI systems"],
        )

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)

    result = discover_jobs_from_web(
        profile=CandidateProfilePayload(
            headline="AI Support Engineer",
            summary="Support leader for AI products.",
            location="London, UK",
            skills=["Python", "SQL"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["AI Support Engineer"],
            target_responsibilities=["Lead customer escalations"],
            locations=["London, UK"],
            workplace_modes=["hybrid"],
            include_keywords=["Python"],
            exclude_keywords=[],
            companies_include=[],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert result.grounded_pages_count == 1
    assert result.jobs[0]["source"] == "greenhouse"
    assert result.jobs[0]["discovery_method"] == "gemini_grounded_search"
    assert result.jobs[0]["external_id"] == "123"
    assert result.jobs[0]["requirements"] == ["3+ years supporting AI systems"]


def test_discover_jobs_from_web_falls_back_to_grounded_source_urls(monkeypatch):
    fetched_urls: list[str] = []

    def fake_search_jobs(self, *, profile, search_preferences):
        assert profile.headline == "Technical Support Manager"
        assert search_preferences.target_titles == ["Technical Support Manager"]
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Swap",
                    title="Technical Support Manager",
                    url="https://jobs.ashbyhq.com/swap/f9e83e6b-7d1c-4b5a-9d2e-6f8b1c4e5a2d",
                    location="London, UK",
                    employment_type="Full-time",
                    source_hint="ashbyhq",
                    description_snippet="Generic shell page candidate.",
                    why_match="Potential role match.",
                )
            ],
            search_queries=["technical support manager swap london"],
            source_urls=[
                "https://jobs.ashbyhq.com/swap",
                "https://jobs.ashbyhq.com/swap/afb66699-257b-482f-993c-8002277a76d6?locationId=39ac34e7-074d-47f8-a523-cebc96cbb99d"
            ],
        )

    def fake_fetch_job_page(url: str):
        fetched_urls.append(url)
        if "f9e83e6b" in url:
            return None
        return FetchedJobPage(
            final_url="https://jobs.ashbyhq.com/swap/afb66699-257b-482f-993c-8002277a76d6",
            canonical_url="https://jobs.ashbyhq.com/swap/afb66699-257b-482f-993c-8002277a76d6",
            page_title="Technical Support Manager @ Swap",
            heading="Technical Support Manager",
            company="Swap",
            location="London, UK",
            employment_type="Full-time",
            description="Lead high-severity technical support escalations across products.",
            requirements=["Experience scaling technical support teams"],
        )

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)
    monkeypatch.setattr(
        "apps.api.app.services.job_discovery.service._discover_recovery_links",
        lambda _url, *, recovery_link_cache: [],
    )

    result = discover_jobs_from_web(
        profile=CandidateProfilePayload(
            headline="Technical Support Manager",
            summary="Technical support leader for AI products.",
            location="London, UK",
            skills=["Python", "incident management"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["Technical Support Manager"],
            target_responsibilities=["Own high-severity technical escalations"],
            locations=["London, UK"],
            workplace_modes=["hybrid"],
            include_keywords=["incident management"],
            exclude_keywords=[],
            companies_include=["Swap"],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert result.grounded_pages_count == 1
    assert len(result.jobs) == 1
    assert result.jobs[0]["source"] == "ashbyhq"
    assert result.jobs[0]["url"] == "https://jobs.ashbyhq.com/swap/afb66699-257b-482f-993c-8002277a76d6"
    assert "https://jobs.ashbyhq.com/swap" not in fetched_urls
    assert result.jobs[0]["metadata_json"]["discovery"]["grounded_url"] == (
        "https://jobs.ashbyhq.com/swap/afb66699-257b-482f-993c-8002277a76d6?locationId=39ac34e7-074d-47f8-a523-cebc96cbb99d"
    )


def test_discover_jobs_from_web_recovers_stale_greenhouse_urls_from_board_links(monkeypatch):
    candidate_url = "https://job-boards.greenhouse.io/anthropic/jobs/4999999999"
    recovered_url = "https://job-boards.greenhouse.io/anthropic/jobs/4980460008"

    def fake_search_jobs(self, *, profile, search_preferences):
        assert profile.headline == "Research Engineer"
        assert search_preferences.target_titles == ["Research Engineer"]
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Anthropic",
                    title="Research Engineer, Production Model Post-Training - London",
                    url=candidate_url,
                    location="London, UK",
                    employment_type="Full-time",
                    source_hint="greenhouse",
                    description_snippet="Production model post-training role.",
                    why_match="Relevant research engineering experience.",
                )
            ],
            search_queries=["research engineer anthropic london greenhouse"],
            source_urls=[],
        )

    def fake_fetch_job_page(url: str):
        if url == candidate_url:
            return None
        if url == recovered_url:
            return FetchedJobPage(
                final_url=recovered_url,
                canonical_url=recovered_url,
                page_title="Research Engineer, Production Model Post-Training - London",
                heading="Research Engineer, Production Model Post-Training - London",
                company="Anthropic",
                location="London, UK",
                location_source="page_text",
                employment_type="Full-time",
                description="Build production post-training systems for large language models.",
                requirements=["Experience with ML systems in production"],
            )
        return None

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)
    monkeypatch.setattr(
        "apps.api.app.services.job_discovery.service._discover_recovery_links",
        lambda url, *, recovery_link_cache: [
            (
                recovered_url,
                "Research Engineer, Production Model Post-Training - London",
            )
        ]
        if url == candidate_url
        else [],
    )

    result = discover_jobs_from_web(
        profile=CandidateProfilePayload(
            headline="Research Engineer",
            summary="Research engineer shipping AI systems.",
            location="London, UK",
            skills=["Python", "machine learning"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["Research Engineer"],
            target_responsibilities=["Ship production AI systems"],
            locations=["London, UK"],
            workplace_modes=["hybrid"],
            include_keywords=["machine learning"],
            exclude_keywords=[],
            companies_include=["Anthropic"],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert len(result.jobs) == 1
    assert result.jobs[0]["url"] == recovered_url
    assert result.jobs[0]["metadata_json"]["discovery"]["grounded_url"] == candidate_url


def test_discover_jobs_from_web_recovers_from_grounding_redirect_wrappers(monkeypatch):
    candidate_url = "https://jobs.ashbyhq.com/sanity/a2180838-8c1d-4054-9541-610fb8d43890"
    wrapper_url = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc123"
    recovered_url = "https://jobs.ashbyhq.com/sanity/ec701d24-cda8-47f4-a58c-a89747f4da23"

    def fake_search_jobs(self, *, profile, search_preferences):
        assert profile.headline == "Support Engineering Manager"
        assert search_preferences.target_titles == ["Support Engineering Manager"]
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Sanity",
                    title="Senior Manager, Support Engineering - Europe",
                    url=candidate_url,
                    location="Remote, Europe",
                    employment_type="Full-time",
                    source_hint="ashbyhq",
                    description_snippet="Lead support engineering in Europe.",
                    why_match="Support leadership overlap.",
                )
            ],
            search_queries=["sanity support engineering manager europe ashby"],
            source_urls=[wrapper_url],
        )

    def fake_fetch_job_page(url: str):
        if url == recovered_url:
            return FetchedJobPage(
                final_url=recovered_url,
                canonical_url=recovered_url,
                page_title="Senior Manager, Support Engineering - Europe",
                heading="Senior Manager, Support Engineering - Europe",
                company="Sanity",
                location="Remote, Europe",
                location_source="page_text",
                employment_type="Full-time",
                description="Lead the support engineering organization across Europe.",
                requirements=["Experience leading support engineering teams"],
            )
        return None

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)
    monkeypatch.setattr(
        "apps.api.app.services.job_discovery.service._discover_recovery_links",
        lambda url, *, recovery_link_cache: [
            (recovered_url, "Senior Manager, Support Engineering - Europe")
        ]
        if url == wrapper_url
        else [],
    )

    result = discover_jobs_from_web(
        profile=CandidateProfilePayload(
            headline="Support Engineering Manager",
            summary="Support engineering leader for SaaS and AI platforms.",
            location="London, UK",
            skills=["support leadership", "incident management"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["Support Engineering Manager"],
            target_responsibilities=["Lead support engineering teams"],
            locations=["Remote, Europe"],
            workplace_modes=["remote"],
            include_keywords=["support leadership"],
            exclude_keywords=[],
            companies_include=["Sanity"],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert len(result.jobs) == 1
    assert result.jobs[0]["url"] == recovered_url
    assert result.jobs[0]["metadata_json"]["discovery"]["grounded_url"] == wrapper_url
    assert result.jobs[0]["metadata_json"]["discovery"]["candidate_url"] == candidate_url


def test_discover_jobs_from_web_rejects_greenhouse_board_pages(monkeypatch):
    def fake_search_jobs(self, *, profile, search_preferences):
        assert profile.headline == "Support Engineer"
        assert search_preferences.target_titles == ["Support Engineer"]
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Canonical",
                    title="Support Engineer",
                    url="https://boards.greenhouse.io/canonical",
                    location="Remote",
                    employment_type="Full-time",
                    source_hint="greenhouse",
                    description_snippet="Customer-facing support role.",
                    why_match="Role family match.",
                )
            ],
            search_queries=["support engineer canonical greenhouse"],
            source_urls=["https://boards.greenhouse.io/canonical"],
        )

    def fake_fetch_job_page(_url: str):
        return FetchedJobPage(
            final_url="https://boards.greenhouse.io/canonical",
            canonical_url="https://boards.greenhouse.io/canonical",
            page_title="Current openings at Canonical",
            heading="Current openings at Canonical",
            company="Canonical",
            location="Remote",
            location_source="page_text",
            employment_type=None,
            description="Browse all open roles across Canonical teams and locations worldwide.",
            requirements=[],
        )

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)
    monkeypatch.setattr(
        "apps.api.app.services.job_discovery.service._discover_recovery_links",
        lambda _url, *, recovery_link_cache: [],
    )

    with pytest.raises(
        WebDiscoveryError,
        match="direct Greenhouse, Lever, or Ashby job posting URLs",
    ):
        discover_jobs_from_web(
            profile=CandidateProfilePayload(
                headline="Support Engineer",
                summary="Technical support engineer for SaaS products.",
                location="London, UK",
                skills=["support"],
                achievements=[],
                experiences=[],
                education=[],
                links={},
            ),
            search_preferences=SearchPreferencesPayload(
                target_titles=["Support Engineer"],
                target_responsibilities=["Handle escalations"],
                locations=["Remote"],
                workplace_modes=["remote"],
                include_keywords=["support"],
                exclude_keywords=[],
                companies_include=["Canonical"],
                companies_exclude=[],
                result_limit=5,
            ),
        )


def test_discover_jobs_from_web_rejects_generic_apply_pages(monkeypatch):
    def fake_search_jobs(self, *, profile, search_preferences):
        assert profile.headline == "Support Manager"
        assert search_preferences.target_titles == ["Support Manager"]
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Example",
                    title="Support Manager",
                    url="https://jobs.example.com/support-manager",
                    location="London, UK",
                    employment_type="Full-time",
                    source_hint=None,
                    description_snippet="Apply on the company website.",
                    why_match="Title overlap.",
                )
            ],
            search_queries=["support manager london"],
            source_urls=["https://jobs.example.com/support-manager"],
        )

    def fake_fetch_job_page(_url: str):
        return FetchedJobPage(
            final_url="https://jobs.example.com/support-manager",
            canonical_url="https://jobs.example.com/support-manager",
            page_title="Support Manager",
            heading="Support Manager",
            company="Example",
            location="London, UK",
            location_source="meta_description",
            employment_type="Full-time",
            description="Support leadership role with a manual apply workflow on the company website.",
            requirements=["Experience leading support teams"],
        )

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)
    monkeypatch.setattr(
        "apps.api.app.services.job_discovery.service._discover_recovery_links",
        lambda _url, *, recovery_link_cache: [],
    )

    with pytest.raises(
        WebDiscoveryError,
        match="direct Greenhouse, Lever, or Ashby job posting URLs",
    ):
        discover_jobs_from_web(
            profile=CandidateProfilePayload(
                headline="Support Manager",
                summary="Support leader for distributed operations.",
                location="London, UK",
                skills=["incident management"],
                achievements=[],
                experiences=[],
                education=[],
                links={},
            ),
            search_preferences=SearchPreferencesPayload(
                target_titles=["Support Manager"],
                target_responsibilities=["Own escalations"],
                locations=["London, UK"],
                workplace_modes=["hybrid"],
                include_keywords=["incident management"],
                exclude_keywords=[],
                companies_include=[],
                companies_exclude=[],
                result_limit=5,
            ),
        )


def test_discover_jobs_from_web_does_not_trust_llm_location_inference(monkeypatch):
    def fake_search_jobs(self, *, profile, search_preferences):
        assert profile.headline == "Support Manager"
        assert search_preferences.locations == ["London, UK"]
        return GroundedSearchResult(
            candidates=[
                GroundedJobCandidate(
                    company="Example",
                    title="Support Manager",
                    url="https://boards.greenhouse.io/example/jobs/123",
                    location="London, UK",
                    employment_type="Full-time",
                    source_hint="greenhouse",
                    description_snippet="Work closely with teams in London and Paris.",
                    why_match="Support leadership overlap.",
                )
            ],
            search_queries=["support manager london"],
            source_urls=["https://boards.greenhouse.io/example/jobs/123"],
        )

    def fake_fetch_job_page(_url: str):
        return FetchedJobPage(
            final_url="https://boards.greenhouse.io/example/jobs/123",
            canonical_url="https://boards.greenhouse.io/example/jobs/123",
            page_title="Example - Support Manager",
            heading="Support Manager",
            company="Example",
            location=None,
            location_source=None,
            employment_type="Full-time",
            description=(
                "This role supports a global team and collaborates with colleagues in London, "
                "Paris, and New York."
            ),
            requirements=["Experience leading support teams"],
        )

    monkeypatch.setattr(GeminiGroundedSearchClient, "search_jobs", fake_search_jobs)
    monkeypatch.setattr("apps.api.app.services.job_discovery.service._fetch_job_page", fake_fetch_job_page)

    result = discover_jobs_from_web(
        profile=CandidateProfilePayload(
            headline="Support Manager",
            summary="Support leader for distributed operations.",
            location="London, UK",
            skills=["incident management"],
            achievements=[],
            experiences=[],
            education=[],
            links={},
        ),
        search_preferences=SearchPreferencesPayload(
            target_titles=["Support Manager"],
            target_responsibilities=["Own escalations"],
            locations=["London, UK"],
            workplace_modes=["hybrid"],
            include_keywords=["incident management"],
            exclude_keywords=[],
            companies_include=[],
            companies_exclude=[],
            result_limit=5,
        ),
    )

    assert len(result.jobs) == 1
    assert result.jobs[0]["location"] is None
    assert result.jobs[0]["metadata_json"]["discovery"]["candidate_location"] == "London, UK"
    assert result.jobs[0]["metadata_json"]["discovery"]["location_source"] is None


def test_web_discovery_route_persists_preferences_and_dedupes_by_url(client, monkeypatch):
    profile_response = client.put(
        "/api/profile",
        json={
            "full_name": "Paul Example",
            "headline": "AI Support Engineer",
            "email": "paul@example.com",
            "phone": None,
            "location": "London, UK",
            "summary": "Support engineer for AI products.",
            "skills": ["Python", "SQL"],
            "achievements": [],
            "experiences": [],
            "education": [],
            "links": {},
        },
    )
    assert profile_response.status_code == 200

    with SessionLocal() as session:
        existing_job = JobLead(
            source="greenhouse",
            external_id="123",
            company="Example",
            title="AI Support Engineer",
            location="London, UK",
            employment_type="Full-time",
            url="https://boards.greenhouse.io/example/jobs/123",
            description="Existing greenhouse role.",
            requirements=[],
            metadata_json={},
            discovery_method="direct",
            score=72.0,
            score_details={"summary": "Existing fit"},
            research={},
            status="discovered",
        )
        session.add(existing_job)
        session.commit()
        session.refresh(existing_job)
        existing_job_id = existing_job.id

    monkeypatch.setattr(
        jobs_router,
        "discover_jobs_from_web",
        lambda **_kwargs: WebDiscoveryResult(
            jobs=[
                {
                    "source": "greenhouse",
                    "discovery_method": "gemini_grounded_search",
                    "external_id": "web-result-123",
                    "company": "Example",
                    "title": "AI Support Engineer",
                    "location": "London, UK",
                    "employment_type": "Full-time",
                    "url": "https://boards.greenhouse.io/example/jobs/123",
                    "description": "Grounded greenhouse role.",
                    "requirements": ["Python"],
                    "metadata_json": {"workplaceType": "Hybrid"},
                }
            ],
            search_queries=["ai support engineer london"],
            source_urls=["https://boards.greenhouse.io/example/jobs/123"],
            grounded_pages_count=1,
        ),
    )

    api_response = client.post(
        "/api/jobs/discover/web",
        json={
            "search_preferences": {
                "target_titles": ["AI Support Engineer"],
                "target_responsibilities": ["Lead customer escalations"],
                "locations": ["London, UK"],
                "workplace_modes": ["hybrid"],
                "include_keywords": ["Python"],
                "exclude_keywords": ["sales"],
                "companies_include": ["Example"],
                "companies_exclude": [],
                "result_limit": 5,
            }
        },
    )

    assert api_response.status_code == 200
    payload = api_response.json()
    assert payload["jobs"][0]["id"] == existing_job_id
    assert payload["jobs"][0]["discovery_method"] == "gemini_grounded_search"
    assert payload["search_queries"] == ["ai support engineer london"]
    assert payload["grounded_pages_count"] == 1
    assert payload["search_preferences"]["exclude_keywords"] == ["sales"]

    with SessionLocal() as session:
        jobs = session.execute(select(JobLead).order_by(JobLead.id)).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].discovery_method == "gemini_grounded_search"

    dashboard_response = client.get("/api/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["profile"]["search_preferences"]["target_titles"] == ["AI Support Engineer"]
