from __future__ import annotations

from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

LEVER_BASE_URL = "https://api.lever.co/v0/postings"


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
def fetch_lever_jobs(company_slug: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        response = client.get(f"{LEVER_BASE_URL}/{company_slug}", params={"mode": "json"})
        response.raise_for_status()
        return [normalize_lever_job(company_slug, job) for job in response.json()]


def normalize_lever_job(company_slug: str, job: dict[str, Any]) -> dict[str, Any]:
    categories = job.get("categories", {})
    lists = [categories.get("team"), categories.get("commitment"), categories.get("location")]
    description_parts = [
        _html_to_text(job.get("descriptionPlain", "") or job.get("description", "")),
        _html_to_text(job.get("lists", [])),
        _html_to_text(job.get("additionalPlain", "") or job.get("additional", "")),
    ]
    description = "\n\n".join(part for part in description_parts if part)
    return {
        "source": "lever",
        "external_id": job.get("id") or job.get("hostedUrl", ""),
        "company": company_slug.replace("-", " ").title(),
        "title": job["text"],
        "location": categories.get("location"),
        "employment_type": categories.get("commitment"),
        "url": job.get("hostedUrl") or job.get("applyUrl") or "",
        "description": description,
        "requirements": [value for value in lists if value],
        "metadata_json": {
            "company_slug": company_slug,
            "categories": categories,
            "workplaceType": job.get("workplaceType"),
            "salaryDescription": job.get("salaryDescription"),
            "team": categories.get("team"),
            "application_questions": job.get("questions", []),
        },
    }


def _html_to_text(content: Any) -> str:
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            text = " ".join(
                section.strip()
                for section in BeautifulSoup(item.get("content", ""), "html.parser")
                .get_text("\n")
                .splitlines()
                if section.strip()
            )
            if item.get("text"):
                chunks.append(f"{item['text']}: {text}".strip())
            elif text:
                chunks.append(text)
        return "\n".join(chunks)
    if "<" not in str(content):
        return str(content).strip()
    return "\n".join(
        line.strip()
        for line in BeautifulSoup(str(content), "html.parser").get_text("\n").splitlines()
        if line.strip()
    )
