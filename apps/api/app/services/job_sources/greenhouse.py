from __future__ import annotations

from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

GREENHOUSE_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


def _should_retry_request(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, httpx.RequestError)


@retry(
    retry=retry_if_exception(_should_retry_request),
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    reraise=True,
)
def fetch_greenhouse_jobs(
    board_token: str, include_questions: bool = False
) -> list[dict[str, Any]]:
    with httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        response = client.get(
            f"{GREENHOUSE_BASE_URL}/{board_token}/jobs", params={"content": "true"}
        )
        response.raise_for_status()
        payload = response.json()

        jobs = payload.get("jobs", [])
        if not include_questions:
            return [normalize_greenhouse_job(board_token, job) for job in jobs]

        detailed_jobs = []
        for job in jobs:
            detail_response = client.get(
                f"{GREENHOUSE_BASE_URL}/{board_token}/jobs/{job['id']}",
                params={"questions": "true"},
            )
            detail_response.raise_for_status()
            detailed_jobs.append(normalize_greenhouse_job(board_token, detail_response.json()))
        return detailed_jobs


def normalize_greenhouse_job(board_token: str, job: dict[str, Any]) -> dict[str, Any]:
    content = _html_to_text(job.get("content", ""))
    location = (job.get("location") or {}).get("name")
    return {
        "source": "greenhouse",
        "external_id": str(job["id"]),
        "company": board_token.replace("-", " ").title(),
        "title": job["title"],
        "location": location,
        "employment_type": ((job.get("metadata") or [{}])[0] or {}).get("value"),
        "url": job.get("absolute_url") or job.get("hostedUrl") or "",
        "description": content,
        "requirements": [],
        "metadata_json": {
            "board_token": board_token,
            "departments": job.get("departments", []),
            "offices": job.get("offices", []),
            "application_questions": {
                "questions": job.get("questions", []),
                "location_questions": job.get("location_questions", []),
                "compliance": job.get("compliance", []),
            },
        },
    }


def _html_to_text(html: str) -> str:
    return "\n".join(
        line.strip()
        for line in BeautifulSoup(html, "html.parser").get_text("\n").splitlines()
        if line.strip()
    )
