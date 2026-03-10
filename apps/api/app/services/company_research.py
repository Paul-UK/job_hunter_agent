from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from apps.api.app.config import settings

IGNORED_HOSTS = {
    "boards.greenhouse.io",
    "api.lever.co",
    "jobs.lever.co",
    "linkedin.com",
    "www.linkedin.com",
}


def research_company(company: str, job_url: str | None = None) -> dict[str, Any]:
    website_summary = summarize_company_website(job_url)
    github_research = summarize_github_org(company)
    return {
        "company": company,
        "website_summary": website_summary.get("summary"),
        "website_url": website_summary.get("url"),
        "github_org": github_research.get("github_org"),
        "github_summary": github_research.get("summary"),
        "top_languages": github_research.get("top_languages", []),
        "notable_repos": github_research.get("notable_repos", []),
    }


def summarize_company_website(job_url: str | None) -> dict[str, str | None]:
    if not job_url:
        return {"url": None, "summary": None}
    parsed = urlparse(job_url)
    host = parsed.netloc.lower().replace("www.", "")
    if host in IGNORED_HOSTS or not host:
        return {"url": None, "summary": None}
    base_url = f"{parsed.scheme or 'https'}://{host}"
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
        return {"url": base_url, "summary": summary}
    except httpx.HTTPError:
        return {"url": base_url, "summary": None}


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
    summary = (
        f"{org_login} shows recent activity in {', '.join(top_languages)}."
        if top_languages
        else f"{org_login} has public repositories worth reviewing."
    )
    return {
        "github_org": org_login,
        "summary": summary,
        "top_languages": top_languages,
        "notable_repos": notable_repos,
    }
