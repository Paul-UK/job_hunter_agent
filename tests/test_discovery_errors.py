from __future__ import annotations

import httpx

from apps.api.app.routers import jobs as jobs_router
from apps.api.app.services.job_discovery import WebDiscoveryError


def test_greenhouse_invalid_board_returns_client_error(client, monkeypatch):
    request = httpx.Request(
        "GET", "https://boards-api.greenhouse.io/v1/boards/openai/jobs?content=true"
    )
    response = httpx.Response(404, request=request)

    def raise_not_found(_board_token: str, include_questions: bool = False):
        raise httpx.HTTPStatusError(
            "Greenhouse board not found",
            request=request,
            response=response,
        )

    monkeypatch.setattr(jobs_router, "fetch_greenhouse_jobs", raise_not_found)

    api_response = client.post(
        "/api/jobs/discover/greenhouse",
        json={"identifiers": ["openai"], "include_questions": False},
    )

    assert api_response.status_code == 400
    assert (
        "Greenhouse board token 'openai' was not found."
        in api_response.json()["detail"]
    )


def test_lever_timeout_returns_gateway_timeout(client, monkeypatch):
    request = httpx.Request("GET", "https://api.lever.co/v0/postings/netflix?mode=json")

    def raise_timeout(_company_slug: str):
        raise httpx.ReadTimeout(
            "Lever timed out",
            request=request,
        )

    monkeypatch.setattr(jobs_router, "fetch_lever_jobs", raise_timeout)

    api_response = client.post(
        "/api/jobs/discover/lever",
        json={"identifiers": ["netflix"]},
    )

    assert api_response.status_code == 504
    assert "Lever timed out while loading 'netflix'." in api_response.json()["detail"]


def test_greenhouse_partial_success_skips_invalid_identifier(client, monkeypatch):
    request = httpx.Request(
        "GET", "https://boards-api.greenhouse.io/v1/boards/bad-board/jobs?content=true"
    )
    not_found_response = httpx.Response(404, request=request)

    def fetch_jobs(board_token: str, include_questions: bool = False):
        if board_token == "bad-board":
            raise httpx.HTTPStatusError(
                "Greenhouse board not found",
                request=request,
                response=not_found_response,
            )
        return [
            {
                "source": "greenhouse",
                "external_id": "123",
                "company": "Good Board",
                "title": "ML Engineer",
                "location": "Remote",
                "employment_type": "Full-time",
                "url": "https://boards.greenhouse.io/good-board/jobs/123",
                "description": "Build ML systems.",
                "requirements": ["Python"],
                "metadata_json": {"board_token": board_token},
            }
        ]

    monkeypatch.setattr(jobs_router, "fetch_greenhouse_jobs", fetch_jobs)

    api_response = client.post(
        "/api/jobs/discover/greenhouse",
        json={"identifiers": ["bad-board", "good-board"], "include_questions": False},
    )

    assert api_response.status_code == 200
    payload = api_response.json()
    assert len(payload) == 1
    assert payload[0]["company"] == "Good Board"


def test_web_discovery_requires_profile_context(client):
    api_response = client.post(
        "/api/jobs/discover/web",
        json={
            "search_preferences": {
                "target_titles": ["AI Engineer"],
                "target_responsibilities": [],
                "locations": ["London, UK"],
                "workplace_modes": [],
                "include_keywords": ["Python"],
                "exclude_keywords": [],
                "companies_include": [],
                "companies_exclude": [],
                "result_limit": 5,
            }
        },
    )

    assert api_response.status_code == 400
    assert "profile" in api_response.json()["detail"].lower()


def test_web_discovery_surfaces_grounded_search_failures(client, monkeypatch):
    profile_response = client.put(
        "/api/profile",
        json={
            "full_name": "Paul Example",
            "headline": "AI Engineer",
            "email": "paul@example.com",
            "phone": None,
            "location": "London, UK",
            "summary": "Python engineer building AI systems.",
            "skills": ["Python", "FastAPI"],
            "achievements": [],
            "experiences": [],
            "education": [],
            "links": {},
        },
    )
    assert profile_response.status_code == 200

    def raise_failure(**_kwargs):
        raise WebDiscoveryError("Gemini grounded search failed: upstream timeout")

    monkeypatch.setattr(jobs_router, "discover_jobs_from_web", raise_failure)

    api_response = client.post(
        "/api/jobs/discover/web",
        json={
            "search_preferences": {
                "target_titles": ["AI Engineer"],
                "target_responsibilities": ["Build AI systems"],
                "locations": ["London, UK"],
                "workplace_modes": [],
                "include_keywords": ["Python"],
                "exclude_keywords": [],
                "companies_include": [],
                "companies_exclude": [],
                "result_limit": 5,
            }
        },
    )

    assert api_response.status_code == 503
    assert "grounded search failed" in api_response.json()["detail"].lower()
