from __future__ import annotations

from collections import Counter
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from apps.api.app.config import settings

IGNORED_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "boards-api.greenhouse.io",
    "api.lever.co",
    "jobs.lever.co",
    "linkedin.com",
    "www.linkedin.com",
}
IGNORED_HOST_SUFFIXES = {
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "ashbyhq.com",
    "workable.com",
    "smartrecruiters.com",
    "jobvite.com",
    "icims.com",
    "taleo.net",
    "recruitee.com",
}
ATS_COPY_PATTERNS = (
    r"\bapplicant tracking software\b",
    r"\bats recruiting software\b",
    r"\bhiring platform\b",
    r"\brecruiting software\b",
    r"\btalent management\b",
)


def research_company(company: str, job_url: str | None = None) -> dict[str, Any]:
    github_research = summarize_github_org(company)
    website_summary = summarize_company_website(
        job_url,
        fallback_url=github_research.get("website_url"),
    )
    return {
        "company": company,
        "website_summary": website_summary.get("summary"),
        "website_url": website_summary.get("url"),
        "github_org": github_research.get("github_org"),
        "github_summary": github_research.get("summary"),
        "org_description": github_research.get("description"),
        "top_languages": github_research.get("top_languages", []),
        "notable_repos": github_research.get("notable_repos", []),
    }


def summarize_company_website(
    job_url: str | None,
    fallback_url: str | None = None,
) -> dict[str, str | None]:
    for candidate_url in [job_url, fallback_url]:
        base_url = _normalize_public_base_url(candidate_url)
        if not base_url:
            continue
        parsed = urlparse(base_url)
        host = parsed.netloc.lower().replace("www.", "")
        if _is_ignored_host(host):
            continue
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(base_url)
                response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            title = (soup.title.string or "").strip() if soup.title else ""
            description_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
                "meta", attrs={"property": "og:description"}
            )
            description = (description_tag.get("content") or "").strip() if description_tag else ""
            summary = ". ".join(part for part in [title, description] if part) or None
            if is_unhelpful_research_text(summary):
                return {"url": base_url, "summary": None}
            return {"url": base_url, "summary": summary}
        except httpx.HTTPError:
            return {"url": base_url, "summary": None}
    return {"url": None, "summary": None}


def summarize_github_org(company: str) -> dict[str, Any]:
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    try:
        with httpx.Client(timeout=10.0, headers=headers) as client:
            search_response = client.get(
                "https://api.github.com/search/users",
                params={"q": f"{company} type:org", "per_page": 1},
            )
            search_response.raise_for_status()
            items = search_response.json().get("items", [])
            if not items:
                return {
                    "github_org": None,
                    "summary": None,
                    "top_languages": [],
                    "notable_repos": [],
                }

            org_login = items[0]["login"]
            org_response = client.get(f"https://api.github.com/orgs/{org_login}")
            org_response.raise_for_status()
            org_payload = org_response.json()
            repos_response = client.get(
                f"https://api.github.com/orgs/{org_login}/repos",
                params={"sort": "updated", "per_page": 5},
            )
            repos_response.raise_for_status()
            repos = repos_response.json()
    except httpx.HTTPError:
        return {"github_org": None, "summary": None, "top_languages": [], "notable_repos": []}

    language_counter = Counter(repo.get("language") for repo in repos if repo.get("language"))
    top_languages = [language for language, _count in language_counter.most_common(4)]
    notable_repos = [
        {
            "name": repo["name"],
            "language": repo.get("language"),
            "stars": repo.get("stargazers_count", 0),
            "updated_at": repo.get("updated_at"),
            "url": repo.get("html_url"),
        }
        for repo in repos
    ]
    org_description = (org_payload.get("description") or "").strip()
    website_url = _normalize_public_base_url(org_payload.get("blog"))
    if org_description and top_languages:
        summary = (
            f"{org_description} Public repositories show recent activity in "
            f"{', '.join(top_languages[:3])}."
        )
    elif org_description:
        summary = org_description
    elif top_languages:
        summary = f"Public repositories show recent activity in {', '.join(top_languages[:3])}."
    else:
        summary = "Public repositories are available for review."
    return {
        "github_org": org_login,
        "summary": summary,
        "description": org_description or None,
        "website_url": website_url,
        "top_languages": top_languages,
        "notable_repos": notable_repos,
    }


def research_needs_refresh(research: dict[str, Any] | None) -> bool:
    if not research:
        return True
    website_url = str(research.get("website_url") or "")
    if website_url:
        host = urlparse(website_url).netloc.lower().replace("www.", "")
        if _is_ignored_host(host):
            return True
    return is_unhelpful_research_text(research.get("website_summary"))


def is_unhelpful_research_text(summary: Any) -> bool:
    if not isinstance(summary, str):
        return False
    normalized_summary = summary.strip()
    if not normalized_summary:
        return False
    lowered = normalized_summary.lower()
    return any(re.search(pattern, lowered) for pattern in ATS_COPY_PATTERNS)


def _normalize_public_base_url(url: str | None) -> str | None:
    if not url:
        return None
    candidate_url = url.strip()
    if not candidate_url:
        return None
    if "://" not in candidate_url:
        candidate_url = f"https://{candidate_url}"
    parsed = urlparse(candidate_url)
    host = parsed.netloc.lower().replace("www.", "")
    if not host or _is_ignored_host(host):
        return None
    return f"{parsed.scheme or 'https'}://{host}"


def _is_ignored_host(host: str) -> bool:
    normalized_host = host.lower().replace("www.", "")
    if not normalized_host:
        return True
    if normalized_host in IGNORED_HOSTS:
        return True
    return any(
        normalized_host == suffix or normalized_host.endswith(f".{suffix}")
        for suffix in IGNORED_HOST_SUFFIXES
    )
