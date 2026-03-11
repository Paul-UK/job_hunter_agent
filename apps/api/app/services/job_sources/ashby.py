from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

ASHBY_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"


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
def fetch_ashby_jobs(job_board_name: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        response = client.get(
            f"{ASHBY_BASE_URL}/{job_board_name}",
            params={"includeCompensation": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        jobs = payload.get("jobs", [])
        return [
            normalize_ashby_job(job_board_name, job)
            for job in jobs
            if job.get("isListed", True)
        ]


def normalize_ashby_job(job_board_name: str, job: dict[str, Any]) -> dict[str, Any]:
    description = (job.get("descriptionPlain") or "").strip() or _html_to_text(
        job.get("descriptionHtml", "")
    )
    location = (job.get("location") or "").strip() or _format_location(job)
    job_url = str(job.get("jobUrl") or "").strip()
    apply_url = str(job.get("applyUrl") or "").strip()

    return {
        "source": "ashbyhq",
        "external_id": _ashby_external_id(job_board_name, job_url, apply_url, job),
        "company": job_board_name.replace("-", " ").replace("_", " ").title(),
        "title": job["title"],
        "location": location or None,
        "employment_type": _humanize_enum(job.get("employmentType")),
        "url": apply_url or job_url,
        "description": description,
        "requirements": [],
        "metadata_json": {
            "job_board_name": job_board_name,
            "job_url": job_url,
            "apply_url": apply_url,
            "department": job.get("department"),
            "team": job.get("team"),
            "is_remote": job.get("isRemote"),
            "is_listed": job.get("isListed", True),
            "workplaceType": job.get("workplaceType"),
            "published_at": job.get("publishedAt"),
            "secondary_locations": job.get("secondaryLocations", []),
            "compensation": job.get("compensation"),
        },
    }


def _ashby_external_id(
    job_board_name: str,
    job_url: str,
    apply_url: str,
    job: dict[str, Any],
) -> str:
    job_path = urlparse(job_url).path.strip("/")
    apply_path = urlparse(apply_url).path.strip("/")
    fallback = f"{job.get('title', '')}:{job.get('publishedAt', '')}".strip(":")
    return f"{job_board_name}:{job_path or apply_path or fallback}"


def _format_location(job: dict[str, Any]) -> str:
    postal_address = ((job.get("address") or {}).get("postalAddress") or {})
    parts = [
        str(postal_address.get("addressLocality") or "").strip(),
        str(postal_address.get("addressRegion") or "").strip(),
        str(postal_address.get("addressCountry") or "").strip(),
    ]
    return ", ".join(part for part in parts if part)


def _humanize_enum(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return re.sub(r"(?<!^)(?=[A-Z])", " ", raw).strip()


def _html_to_text(html: str) -> str:
    return "\n".join(
        line.strip()
        for line in BeautifulSoup(html, "html.parser").get_text("\n").splitlines()
        if line.strip()
    )
