from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from apps.api.app.config import settings
from apps.api.app.schemas import CandidateProfilePayload, SearchPreferencesPayload

SUPPORTED_APPLY_PLATFORMS = {"greenhouse", "lever", "ashbyhq"}
SEARCH_SOURCE_HINTS = SUPPORTED_APPLY_PLATFORMS
ATS_INDEX_PAGE_TITLES = {"jobs", "careers", "open roles", "current openings"}
ATS_INDEX_PAGE_PREFIXES = ("current openings at ", "open roles at ")
GENERIC_APPLY_LINK_TEXT = {
    "apply",
    "apply now",
    "apply here",
    "apply for this position",
    "learn more",
    "view job",
    "view role",
}
GROUNDING_REDIRECT_HOSTS = {"vertexaisearch.cloud.google.com"}
IGNORED_SEARCH_HOSTS = {
    "google.com",
    "www.google.com",
    "linkedin.com",
    "www.linkedin.com",
    "glassdoor.com",
    "www.glassdoor.com",
    "indeed.com",
    "www.indeed.com",
}
SCHEMA_JOB_TYPES = {"jobposting", "job posting"}
REQUIREMENT_SECTION_TERMS = (
    "requirements",
    "qualifications",
    "what you bring",
    "must have",
    "you will need",
)


class WebDiscoveryError(RuntimeError):
    pass


class RetryableWebDiscoveryError(WebDiscoveryError):
    pass


@dataclass(slots=True)
class GroundedJobCandidate:
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    employment_type: str | None = None
    source_hint: str | None = None
    description_snippet: str | None = None
    why_match: str | None = None


@dataclass(slots=True)
class GroundedSearchResult:
    candidates: list[GroundedJobCandidate]
    search_queries: list[str]
    source_urls: list[str]


@dataclass(slots=True)
class FetchedJobPage:
    final_url: str
    canonical_url: str | None = None
    page_title: str | None = None
    heading: str | None = None
    company: str | None = None
    location: str | None = None
    location_source: str | None = None
    employment_type: str | None = None
    description: str | None = None
    requirements: list[str] | None = None


@dataclass(slots=True)
class WebDiscoveryResult:
    jobs: list[dict[str, Any]]
    search_queries: list[str]
    source_urls: list[str]
    grounded_pages_count: int
    diagnostics: dict[str, Any] = field(default_factory=dict)


class GeminiGroundedSearchClient:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def search_jobs(
        self,
        *,
        profile: CandidateProfilePayload,
        search_preferences: SearchPreferencesPayload,
    ) -> GroundedSearchResult:
        if not self.api_key:
            raise WebDiscoveryError(
                "Configure JOB_AGENT_GEMINI_API_KEY before running AI web discovery."
            )

        genai, types = _import_genai_sdk()
        client = genai.Client(api_key=self.api_key)
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        prompt = _build_discovery_prompt(profile, search_preferences)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(tools=[grounding_tool]),
            )
        except Exception as exc:  # pragma: no cover - depends on external SDK/runtime
            raise RetryableWebDiscoveryError(f"Gemini grounded search failed: {exc}") from exc

        response_text = _extract_response_text(response)
        payload = _parse_json_response_text(response_text)
        candidates = _parse_candidates(payload)
        if not candidates:
            raise RetryableWebDiscoveryError(
                "Gemini grounded search did not return any structured job candidates."
            )

        grounding_metadata = _extract_grounding_metadata(response)
        return GroundedSearchResult(
            candidates=candidates,
            search_queries=_extract_search_queries(grounding_metadata),
            source_urls=_extract_source_urls(grounding_metadata),
        )


def discover_jobs_from_web(
    *,
    profile: CandidateProfilePayload,
    search_preferences: SearchPreferencesPayload,
) -> WebDiscoveryResult:
    client = GeminiGroundedSearchClient(
        api_key=settings.gemini_api_key or "",
        model=settings.gemini_discovery_model,
        timeout_seconds=settings.gemini_discovery_timeout_seconds,
    )
    max_attempts = max(1, settings.gemini_discovery_max_attempts)
    last_error: RetryableWebDiscoveryError | None = None
    for _attempt in range(1, max_attempts + 1):
        try:
            return _discover_jobs_from_web_attempt(
                client=client,
                profile=profile,
                search_preferences=search_preferences,
            )
        except RetryableWebDiscoveryError as exc:
            last_error = exc
    if last_error is not None:
        raise _format_retry_exhausted_error(last_error, max_attempts)
    raise WebDiscoveryError("AI web discovery failed before Gemini returned a usable result.")


def _discover_jobs_from_web_attempt(
    *,
    client: GeminiGroundedSearchClient,
    profile: CandidateProfilePayload,
    search_preferences: SearchPreferencesPayload,
) -> WebDiscoveryResult:
    search_result = client.search_jobs(profile=profile, search_preferences=search_preferences)

    jobs: list[dict[str, Any]] = []
    fetched_urls: list[str] = []
    rejected_pages_count = 0
    normalized_source_urls: list[tuple[str, str]] = []
    recovery_link_cache: dict[str, list[tuple[str, str | None]]] = {}
    for url in search_result.source_urls:
        normalized_url = _normalize_url(url)
        if normalized_url:
            normalized_source_urls.append((url, normalized_url))
    source_urls = _dedupe_candidate_attempts(normalized_source_urls)
    seen_final_urls: set[str] = set()
    for candidate in search_result.candidates[: search_preferences.result_limit]:
        payload, candidate_fetched_urls, candidate_rejections = _resolve_grounded_candidate(
            candidate,
            source_urls=source_urls,
            seen_final_urls=seen_final_urls,
            recovery_link_cache=recovery_link_cache,
        )
        fetched_urls.extend(candidate_fetched_urls)
        rejected_pages_count += candidate_rejections
        if payload is not None:
            jobs.append(payload)

    if not jobs:
        if rejected_pages_count > 0:
            raise RetryableWebDiscoveryError(
                "Gemini returned ATS results, but none were direct Greenhouse, Lever, or Ashby job posting URLs."
            )
        raise RetryableWebDiscoveryError(
            "Gemini grounded search did not return any job pages that could be normalized."
        )

    source_urls = _dedupe([*search_result.source_urls, *fetched_urls])
    return WebDiscoveryResult(
        jobs=jobs,
        search_queries=search_result.search_queries,
        source_urls=source_urls,
        grounded_pages_count=len(fetched_urls),
        diagnostics={
            "candidate_count": len(search_result.candidates),
            "accepted_job_count": len(jobs),
            "rejected_pages_count": rejected_pages_count,
            "fetched_url_count": len(fetched_urls),
            "source_url_count": len(search_result.source_urls),
        },
    )


def _import_genai_sdk():
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - guarded by runtime environment
        raise WebDiscoveryError(
            "The google-genai package is required for Gemini grounded discovery."
        ) from exc
    return genai, types


def _build_discovery_prompt(
    profile: CandidateProfilePayload,
    search_preferences: SearchPreferencesPayload,
) -> str:
    prompt = {
        "task": "Find current live job postings that match this candidate and search intent.",
        "constraints": [
            "Use Google Search grounding to find current public job pages.",
            "Only keep jobs whose final URL is a direct Greenhouse, Lever, or Ashby job posting page.",
            "Never return ATS board homepages, careers indexes, 'Current openings at ...' pages, or listing pages.",
            "Prefer direct ATS application pages over company marketing pages and ATS board shells.",
            "Exclude jobs that require email application, manual website forms, or unsupported ATS platforms.",
            "Avoid LinkedIn, Glassdoor, Indeed, and search result pages unless no official source exists.",
            "Return JSON only.",
            "Each candidate must include a direct job URL.",
            "Set source_hint to one of: greenhouse, lever, ashbyhq.",
        ],
        "candidate_profile": {
            "headline": profile.headline,
            "summary": profile.summary,
            "location": profile.location,
            "skills": profile.skills[:10],
            "recent_titles": [experience.title for experience in profile.experiences[:5] if experience.title],
            "recent_highlights": [
                highlight
                for experience in profile.experiences[:4]
                for highlight in experience.highlights[:2]
            ][:6],
        },
        "search_preferences": search_preferences.model_dump(mode="json"),
        "response_shape": {
            "candidates": [
                {
                    "company": "string",
                    "title": "string",
                    "url": "string",
                    "location": "string or null",
                    "employment_type": "string or null",
                    "source_hint": "greenhouse|lever|ashbyhq",
                    "description_snippet": "string or null",
                    "why_match": "string",
                }
            ]
        },
    }
    return "Return valid JSON only.\n" + json.dumps(prompt, ensure_ascii=True, indent=2)


def _parse_json_response_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    if not cleaned:
        return {}
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RetryableWebDiscoveryError("Gemini grounded search returned invalid JSON.") from exc
    return payload if isinstance(payload, dict) else {}


def _format_retry_exhausted_error(
    error: RetryableWebDiscoveryError,
    attempts: int,
) -> WebDiscoveryError:
    detail = str(error).strip().rstrip(".")
    return WebDiscoveryError(
        f"AI web discovery failed after {attempts} Gemini attempt{'s' if attempts != 1 else ''}. "
        f"{detail}. Try again shortly or use Manual ATS Discovery."
    )


def _extract_response_text(response: Any) -> str:
    direct_text = getattr(response, "text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text

    candidates = getattr(response, "candidates", None) or []
    parts_text: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content is None and isinstance(candidate, dict):
            content = candidate.get("content")
        parts = getattr(content, "parts", None) if content is not None else None
        if parts is None and isinstance(content, dict):
            parts = content.get("parts")
        for part in parts or []:
            text = getattr(part, "text", None)
            if text is None and isinstance(part, dict):
                text = part.get("text")
            if isinstance(text, str) and text.strip():
                parts_text.append(text)
    if parts_text:
        return "\n".join(parts_text)
    return direct_text if isinstance(direct_text, str) else ""


def _parse_candidates(payload: dict[str, Any]) -> list[GroundedJobCandidate]:
    raw_candidates = payload.get("candidates") or payload.get("jobs") or []
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[GroundedJobCandidate] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        url = _normalize_url(item.get("url"))
        if not title or not url:
            continue
        source_hint = _clean_text(item.get("source_hint"))
        if source_hint not in SEARCH_SOURCE_HINTS:
            source_hint = None
        candidates.append(
            GroundedJobCandidate(
                title=title,
                url=url,
                company=_clean_text(item.get("company")),
                location=_clean_text(item.get("location")),
                employment_type=_clean_text(item.get("employment_type")),
                source_hint=source_hint,
                description_snippet=_clean_text(item.get("description_snippet")),
                why_match=_clean_text(item.get("why_match")),
            )
        )
    return candidates


def _extract_grounding_metadata(response: Any) -> dict[str, Any]:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return {}
    candidate = candidates[0]
    metadata = getattr(candidate, "grounding_metadata", None)
    if metadata is None and isinstance(candidate, dict):
        metadata = candidate.get("grounding_metadata") or candidate.get("groundingMetadata")
    normalized = _to_plain_data(metadata)
    return normalized if isinstance(normalized, dict) else {}


def _extract_search_queries(metadata: dict[str, Any]) -> list[str]:
    raw_queries = metadata.get("web_search_queries") or metadata.get("webSearchQueries") or []
    queries: list[str] = []
    for item in raw_queries:
        if isinstance(item, str):
            queries.append(item.strip())
            continue
        if isinstance(item, dict):
            query = item.get("query") or item.get("text")
            if isinstance(query, str):
                queries.append(query.strip())
    return _dedupe([query for query in queries if query])


def _extract_source_urls(metadata: dict[str, Any]) -> list[str]:
    raw_chunks = metadata.get("grounding_chunks") or metadata.get("groundingChunks") or []
    urls: list[str] = []
    for chunk in raw_chunks:
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web") or {}
        if isinstance(web, dict):
            uri = _normalize_url(web.get("uri"))
            if uri:
                urls.append(uri)
    return _dedupe(urls)


def _fetch_job_page(url: str) -> FetchedJobPage | None:
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": "PT Job Hunting Agent/1.0"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError:
        return None

    final_url = _normalize_url(str(response.url)) or url
    soup = BeautifulSoup(response.text, "html.parser")
    schema_payload = _parse_job_posting_schema(soup)
    canonical_url = _canonical_page_url(soup) or final_url
    page_title = _clean_text(soup.title.string if soup.title and soup.title.string else "")
    heading = _clean_text(schema_payload.get("title")) or _first_text(soup, ["h1", "main h1", "article h1"])
    location, location_source = _extract_page_location(soup, schema_payload)
    description = (
        _clean_text(schema_payload.get("description"))
        or _extract_description_text(soup)
    )
    if not _looks_like_job_page(
        page_title=page_title,
        heading=heading,
        description=description,
        schema_payload=schema_payload,
    ):
        return None
    requirements = _extract_requirement_lines(description)
    return FetchedJobPage(
        final_url=final_url,
        canonical_url=canonical_url,
        page_title=page_title,
        heading=heading,
        company=_clean_text(schema_payload.get("company")),
        location=location,
        location_source=location_source,
        employment_type=_clean_text(schema_payload.get("employment_type")),
        description=description,
        requirements=requirements,
    )


def _parse_job_posting_schema(soup: BeautifulSoup) -> dict[str, str]:
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        if not script.string and not script.text:
            continue
        raw_content = script.string or script.text
        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError:
            continue
        job_posting = _find_job_posting(payload)
        if job_posting:
            description = job_posting.get("description")
            if isinstance(description, str) and "<" in description:
                description = _html_to_text(description)
            return {
                "title": str(job_posting.get("title") or "").strip(),
                "description": str(description or "").strip(),
                "company": _extract_company_name(job_posting.get("hiringOrganization")),
                "location": _extract_job_location(job_posting.get("jobLocation")),
                "employment_type": str(job_posting.get("employmentType") or "").strip(),
            }
    return {}


def _find_job_posting(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, list):
        for item in payload:
            result = _find_job_posting(item)
            if result:
                return result
        return None
    if not isinstance(payload, dict):
        return None
    raw_type = payload.get("@type") or payload.get("type")
    if isinstance(raw_type, list):
        normalized_types = {str(item).strip().lower() for item in raw_type}
    else:
        normalized_types = {str(raw_type).strip().lower()} if raw_type else set()
    if normalized_types & SCHEMA_JOB_TYPES:
        return payload
    for value in payload.values():
        result = _find_job_posting(value)
        if result:
            return result
    return None


def _extract_company_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "").strip()
    if isinstance(value, list):
        for item in value:
            company_name = _extract_company_name(item)
            if company_name:
                return company_name
    if isinstance(value, str):
        return value.strip()
    return ""


def _extract_job_location(value: Any) -> str:
    locations: list[str] = []
    if isinstance(value, list):
        for item in value:
            location = _extract_job_location(item)
            if location:
                locations.append(location)
        return ", ".join(_dedupe(locations))
    if not isinstance(value, dict):
        return ""
    address = value.get("address") or {}
    if isinstance(address, dict):
        parts = [
            str(address.get("addressLocality") or "").strip(),
            str(address.get("addressRegion") or "").strip(),
            str(address.get("addressCountry") or "").strip(),
        ]
        return ", ".join(part for part in parts if part)
    return str(value.get("name") or "").strip()


def _extract_description_text(soup: BeautifulSoup) -> str | None:
    candidates: list[str] = []
    for selector in [
        "main",
        "article",
        "[role='main']",
        ".job-description",
        ".jobDescription",
        ".description",
        ".posting",
        "#content",
    ]:
        for node in soup.select(selector):
            text = _clean_text(node.get_text("\n", strip=True))
            if text:
                candidates.append(text)
    if not candidates:
        meta_description = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        if meta_description:
            return _clean_text(meta_description.get("content"))
        return None
    return max(candidates, key=len)


def _extract_requirement_lines(description: str | None) -> list[str]:
    if not description:
        return []
    section_lines = []
    capture = False
    for line in description.splitlines():
        normalized_line = line.strip()
        lowered = normalized_line.lower()
        if any(term in lowered for term in REQUIREMENT_SECTION_TERMS):
            capture = True
            continue
        if capture and normalized_line:
            section_lines.append(normalized_line.lstrip("-• "))
        if capture and not normalized_line:
            break
    if section_lines:
        return _dedupe(section_lines)[:8]
    heuristic_lines = [
        line.strip().lstrip("-• ")
        for line in description.splitlines()
        if 20 <= len(line.strip()) <= 180
        and any(keyword in line.lower() for keyword in ("experience", "knowledge", "ability", "proficient"))
    ]
    return _dedupe(heuristic_lines)[:6]


def _resolve_grounded_candidate(
    candidate: GroundedJobCandidate,
    *,
    source_urls: list[tuple[str, str]],
    seen_final_urls: set[str],
    recovery_link_cache: dict[str, list[tuple[str, str | None]]],
) -> tuple[dict[str, Any] | None, list[str], int]:
    fetched_urls: list[str] = []
    rejected_pages_count = 0
    attempted_urls: set[str] = set()
    pending_attempts = list(_candidate_attempt_urls(candidate, source_urls))
    while pending_attempts:
        grounded_url, fetch_url = pending_attempts.pop(0)
        attempt_key = fetch_url.casefold()
        if attempt_key in attempted_urls:
            continue
        attempted_urls.add(attempt_key)
        page = _fetch_job_page(fetch_url)
        if page is None:
            recovery_attempts = _recovery_attempt_urls(
                candidate,
                grounded_url=grounded_url,
                recovery_links=_discover_recovery_links(
                    fetch_url,
                    recovery_link_cache=recovery_link_cache,
                ),
                attempted_urls=attempted_urls,
            )
            if recovery_attempts:
                pending_attempts = [*recovery_attempts, *pending_attempts]
            continue
        fetched_urls.append(page.final_url)
        canonical_seen_url = page.canonical_url or page.final_url
        if canonical_seen_url in seen_final_urls:
            continue
        if not _page_matches_candidate(candidate, page):
            rejected_pages_count += 1
        else:
            payload = _normalize_grounded_job(candidate, page=page, grounded_url=grounded_url)
            if payload is not None:
                seen_final_urls.add(canonical_seen_url)
                return payload, fetched_urls, rejected_pages_count
            rejected_pages_count += 1
        recovery_attempts = _recovery_attempt_urls(
            candidate,
            grounded_url=grounded_url,
            recovery_links=_discover_recovery_links(
                fetch_url,
                recovery_link_cache=recovery_link_cache,
            ),
            attempted_urls=attempted_urls,
        )
        if recovery_attempts:
            pending_attempts = [*recovery_attempts, *pending_attempts]
    return None, fetched_urls, rejected_pages_count


def _candidate_attempt_urls(
    candidate: GroundedJobCandidate,
    source_urls: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    primary_url = _normalize_url(candidate.url)
    if not primary_url:
        return []
    attempts = [(candidate.url, primary_url)]
    candidate_source = (
        candidate.source_hint
        if candidate.source_hint in SUPPORTED_APPLY_PLATFORMS
        else _detect_apply_platform(primary_url)
    )
    company_key = _match_key(candidate.company)
    fallback_urls: list[tuple[str, str]] = []
    for raw_url, normalized_url in source_urls:
        if normalized_url == primary_url:
            continue
        source = _detect_apply_platform(normalized_url)
        if source in SUPPORTED_APPLY_PLATFORMS:
            if candidate_source in SUPPORTED_APPLY_PLATFORMS and source != candidate_source:
                continue
            if not _is_supported_job_detail_url(normalized_url, source):
                continue
            if company_key and company_key not in _match_key(normalized_url):
                continue
            fallback_urls.append((raw_url, normalized_url))
            continue
        if _should_probe_source_url(normalized_url):
            fallback_urls.append((raw_url, normalized_url))
    return _dedupe_candidate_attempts([*attempts, *fallback_urls])


def _discover_recovery_links(
    url: str,
    *,
    recovery_link_cache: dict[str, list[tuple[str, str | None]]],
) -> list[tuple[str, str | None]]:
    normalized_url = _normalize_url(url)
    if not normalized_url:
        return []
    cached = recovery_link_cache.get(normalized_url)
    if cached is not None:
        return cached
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": "PT Job Hunting Agent/1.0"},
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError:
        recovery_link_cache[normalized_url] = []
        return []

    final_url = _normalize_url(str(response.url)) or normalized_url
    soup = BeautifulSoup(response.text, "html.parser")
    page_title = _clean_text(soup.title.string if soup.title and soup.title.string else "")
    heading = _first_text(soup, ["h1", "main h1", "article h1"])
    discovered_links = _extract_supported_apply_links(
        soup,
        base_url=final_url,
        page_title=page_title,
        heading=heading,
    )
    recovery_link_cache[normalized_url] = discovered_links
    recovery_link_cache.setdefault(final_url, discovered_links)
    return discovered_links


def _extract_supported_apply_links(
    soup: BeautifulSoup,
    *,
    base_url: str,
    page_title: str | None,
    heading: str | None,
) -> list[tuple[str, str | None]]:
    context_label = heading or page_title
    discovered_links: list[tuple[str, str | None]] = []
    normalized_base_url = _normalize_recovered_job_url(base_url)
    base_source = _detect_apply_platform(normalized_base_url) if normalized_base_url else "generic"
    if (
        normalized_base_url
        and base_source in SUPPORTED_APPLY_PLATFORMS
        and _is_supported_job_detail_url(normalized_base_url, base_source)
    ):
        discovered_links.append((normalized_base_url, context_label))

    for node in soup.select("a[href]"):
        href = node.get("href")
        candidate_url = _normalize_recovered_job_url(urljoin(base_url, str(href or "")))
        if not candidate_url or _is_ignored_search_host(candidate_url):
            continue
        source = _detect_apply_platform(candidate_url)
        if source not in SUPPORTED_APPLY_PLATFORMS:
            continue
        if not _is_supported_job_detail_url(candidate_url, source):
            continue
        label = _clean_text(node.get_text(" ", strip=True)) or _clean_text(node.get("aria-label"))
        if _is_generic_apply_link_text(label):
            label = context_label or label
        discovered_links.append((candidate_url, label or context_label))
    return _dedupe_recovery_links(discovered_links)


def _normalize_recovered_job_url(url: str) -> str | None:
    normalized_url = _normalize_url(url)
    if not normalized_url:
        return None
    source = _detect_apply_platform(normalized_url)
    if source not in SUPPORTED_APPLY_PLATFORMS:
        return normalized_url
    parsed = urlsplit(normalized_url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if source in {"ashbyhq", "greenhouse"} and segments and segments[-1].casefold() == "application":
        segments = segments[:-1]
    if source == "lever" and segments and segments[-1].casefold() == "apply":
        segments = segments[:-1]
    normalized_path = "/" + "/".join(segments) if segments else ""
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def _recovery_attempt_urls(
    candidate: GroundedJobCandidate,
    *,
    grounded_url: str,
    recovery_links: list[tuple[str, str | None]],
    attempted_urls: set[str],
) -> list[tuple[str, str]]:
    scored_links: list[tuple[int, str]] = []
    for recovery_url, label in recovery_links:
        if recovery_url.casefold() in attempted_urls:
            continue
        score = _recovery_link_score(candidate, recovery_url, label)
        if score <= 0:
            continue
        scored_links.append((score, recovery_url))
    scored_links.sort(key=lambda item: item[0], reverse=True)
    return [(grounded_url, recovery_url) for _score, recovery_url in scored_links[:8]]


def _recovery_link_score(
    candidate: GroundedJobCandidate,
    url: str,
    label: str | None,
) -> int:
    haystack = " ".join(part for part in [label or "", url] if part)
    haystack_key = _match_key(haystack)
    haystack_tokens = _match_tokens(haystack)
    if not haystack_key or not haystack_tokens:
        return 0

    score = 0
    candidate_key = _match_key(candidate.title)
    candidate_title_tokens = _match_tokens(candidate.title)
    if candidate_key:
        if candidate_key in haystack_key or haystack_key in candidate_key:
            score += 100
        else:
            shared_title_tokens = len(candidate_title_tokens & haystack_tokens)
            if candidate_title_tokens and shared_title_tokens == 0:
                return 0
            if shared_title_tokens == 1 and len(candidate_title_tokens) > 1:
                return 0
            score += shared_title_tokens * 10

    candidate_company_tokens = _match_tokens(candidate.company)
    score += len(candidate_company_tokens & haystack_tokens) * 4
    if candidate.source_hint in SUPPORTED_APPLY_PLATFORMS and _detect_apply_platform(url) == candidate.source_hint:
        score += 3
    return score


def _should_probe_source_url(url: str) -> bool:
    if _is_ignored_search_host(url):
        return False
    parsed = urlsplit(url)
    host = parsed.netloc.lower().replace("www.", "")
    if host in GROUNDING_REDIRECT_HOSTS:
        return True
    normalized_path = parsed.path.casefold()
    return any(fragment in normalized_path for fragment in ("/career", "/careers", "/job", "/jobs"))


def _is_generic_apply_link_text(value: str | None) -> bool:
    normalized = " ".join(str(value or "").strip().casefold().split())
    return not normalized or normalized in GENERIC_APPLY_LINK_TEXT


def _page_matches_candidate(
    candidate: GroundedJobCandidate,
    page: FetchedJobPage,
) -> bool:
    if candidate.company and page.company:
        if _match_key(candidate.company) != _match_key(page.company):
            return False

    candidate_key = _match_key(candidate.title)
    page_key = _match_key(page.heading or page.page_title)
    if not candidate_key or not page_key:
        return True
    if candidate_key in page_key or page_key in candidate_key:
        return True

    candidate_tokens = _match_tokens(candidate.title)
    page_tokens = _match_tokens(page.heading or page.page_title)
    if not candidate_tokens or not page_tokens:
        return False
    shared_tokens = candidate_tokens & page_tokens
    required_overlap = max(2, min(len(candidate_tokens), len(page_tokens), 3))
    return len(shared_tokens) >= required_overlap


def _is_supported_job_detail_url(url: str, source: str) -> bool:
    segments = [segment.casefold() for segment in urlsplit(url).path.split("/") if segment]
    if source == "greenhouse":
        if "jobs" not in segments:
            return False
        jobs_index = segments.index("jobs")
        return jobs_index < len(segments) - 1
    if source in {"lever", "ashbyhq"}:
        return len(segments) >= 2
    return False


def _normalize_grounded_job(
    candidate: GroundedJobCandidate,
    *,
    page: FetchedJobPage | None,
    grounded_url: str | None = None,
) -> dict[str, Any] | None:
    if page is None:
        return None
    final_url = (
        page.canonical_url
        if page is not None and page.canonical_url
        else page.final_url
    )
    normalized_url = _normalize_url(final_url)
    if not normalized_url or _is_ignored_search_host(normalized_url):
        return None

    source = _detect_apply_platform(normalized_url)
    if source not in SUPPORTED_APPLY_PLATFORMS:
        return None
    if not _is_supported_job_detail_url(normalized_url, source):
        return None
    title = (page.heading if page is not None else None) or candidate.title
    company = (
        (page.company if page is not None else None)
        or candidate.company
        or _infer_company_from_url(normalized_url)
    )
    description = (
        (page.description if page is not None else None)
        or candidate.description_snippet
        or ""
    )
    requirements = page.requirements if page is not None and page.requirements is not None else []
    location = page.location if page is not None else None
    employment_type = (
        (page.employment_type if page is not None else None)
        or candidate.employment_type
    )
    workplace_type = _infer_workplace_type(location, description)
    metadata_json = {
        "workplaceType": workplace_type,
        "source_hint": candidate.source_hint,
        "discovery": {
            "grounded_url": grounded_url or candidate.url,
            "candidate_url": candidate.url if grounded_url and grounded_url != candidate.url else None,
            "canonical_url": page.canonical_url if page is not None else None,
            "page_title": page.page_title if page is not None else None,
            "location_source": page.location_source if page is not None else None,
            "candidate_location": candidate.location,
            "why_match": candidate.why_match,
        },
    }
    if not title or not company:
        return None
    return {
        "source": source,
        "discovery_method": "gemini_grounded_search",
        "external_id": _external_id_from_url(source, normalized_url),
        "company": company,
        "title": title,
        "location": location,
        "employment_type": employment_type,
        "url": normalized_url,
        "description": description,
        "requirements": requirements,
        "metadata_json": {key: value for key, value in metadata_json.items() if value},
    }


def _detect_apply_platform(url: str) -> str:
    lowered_url = url.lower()
    if "greenhouse" in lowered_url:
        return "greenhouse"
    if "lever.co" in lowered_url:
        return "lever"
    if "ashbyhq.com" in lowered_url:
        return "ashbyhq"
    return "generic"


def _external_id_from_url(source: str, url: str) -> str:
    normalized_url = _normalize_url(url) or url
    path = urlsplit(normalized_url).path.strip("/")
    if source == "greenhouse":
        match = re.search(r"/jobs/([^/?#]+)", normalized_url)
        if match:
            return match.group(1)
    if source == "ashbyhq":
        return path or normalized_url
    if source == "lever":
        return normalized_url
    return normalized_url


def _infer_workplace_type(location: str | None, description: str | None) -> str | None:
    combined = " ".join(part for part in [location or "", description or ""]).lower()
    if "hybrid" in combined:
        return "Hybrid"
    if "remote" in combined or "distributed" in combined:
        return "Remote"
    if "on-site" in combined or "on site" in combined or "onsite" in combined:
        return "On-site"
    return None


def _normalize_url(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, host, path, "", ""))


def _canonical_page_url(soup: BeautifulSoup) -> str | None:
    for selector, attribute in [
        ("link[rel='canonical']", "href"),
        ("meta[property='og:url']", "content"),
    ]:
        node = soup.select_one(selector)
        if node is None:
            continue
        normalized = _normalize_url(node.get(attribute))
        if normalized:
            return normalized
    return None


def _extract_page_location(
    soup: BeautifulSoup, schema_payload: dict[str, str]
) -> tuple[str | None, str | None]:
    schema_location = _clean_text(schema_payload.get("location"))
    if schema_location:
        return schema_location, "schema_jobLocation"

    for selector in [
        "meta[name='description']",
        "meta[property='og:description']",
    ]:
        node = soup.select_one(selector)
        if node is None:
            continue
        location = _extract_explicit_location_text(str(node.get("content") or ""))
        if location:
            return location, "meta_description"

    body_location = _extract_explicit_location_text(soup.get_text("\n", strip=True))
    if body_location:
        return body_location, "page_text"

    return None, None


def _extract_explicit_location_text(text: str) -> str | None:
    lines = [" ".join(line.strip().split()) for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        lowered = line.casefold()
        if lowered.startswith("location:") or lowered.startswith("locations:"):
            _, _, remainder = line.partition(":")
            candidate = remainder.strip(" -")
            if candidate:
                return candidate
            if index + 1 < len(lines):
                next_line = lines[index + 1].strip(" -")
                if next_line:
                    return next_line
    return None


def _looks_like_job_page(
    *,
    page_title: str | None,
    heading: str | None,
    description: str | None,
    schema_payload: dict[str, str],
) -> bool:
    if schema_payload:
        return True
    normalized_title = (page_title or "").strip().casefold()
    normalized_heading = (heading or "").strip().casefold()
    if (
        normalized_title in ATS_INDEX_PAGE_TITLES
        or normalized_heading in ATS_INDEX_PAGE_TITLES
        or any(normalized_title.startswith(prefix) for prefix in ATS_INDEX_PAGE_PREFIXES)
        or any(normalized_heading.startswith(prefix) for prefix in ATS_INDEX_PAGE_PREFIXES)
    ):
        return False
    if heading and description and len(description) >= 120:
        return True
    return bool(heading and normalized_title and normalized_title != heading.strip().casefold())


def _is_ignored_search_host(url: str) -> bool:
    host = urlsplit(url).netloc.lower().replace("www.", "")
    return host in {value.replace("www.", "") for value in IGNORED_SEARCH_HOSTS}


def _infer_company_from_url(url: str) -> str:
    host = urlsplit(url).netloc.lower().replace("www.", "")
    first_label = host.split(".", 1)[0]
    return first_label.replace("-", " ").replace("_", " ").title()


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        text = _clean_text(node.get_text(" ", strip=True))
        if text:
            return text
    return None


def _html_to_text(html: str) -> str:
    return "\n".join(
        line.strip()
        for line in BeautifulSoup(html, "html.parser").get_text("\n").splitlines()
        if line.strip()
    )


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    candidate = re.sub(r"\s+", " ", candidate)
    return candidate[:6000]


def _match_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _match_tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").casefold())
        if len(token) >= 3
    }


def _to_plain_data(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain_data(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _to_plain_data(value.model_dump())
    if hasattr(value, "to_dict"):
        return _to_plain_data(value.to_dict())
    if hasattr(value, "__dict__"):
        return _to_plain_data(vars(value))
    return str(value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _dedupe_candidate_attempts(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for raw_url, normalized_url in values:
        key = normalized_url.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append((raw_url, normalized_url))
    return result


def _dedupe_recovery_links(values: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    seen: set[str] = set()
    result: list[tuple[str, str | None]] = []
    for url, label in values:
        key = url.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append((url, label))
    return result
