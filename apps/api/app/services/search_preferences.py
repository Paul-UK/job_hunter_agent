from __future__ import annotations

import re

from apps.api.app.schemas import CandidateProfilePayload, SearchPreferencesPayload

DEFAULT_RESULT_LIMIT = 10
_TITLE_SPLIT_PATTERN = re.compile(r"\s+\|\s+|\s+/\s+|\s+-\s+")
_SENTENCE_SPLIT_PATTERN = re.compile(r"[\n.;]+")


def seed_search_preferences(profile: CandidateProfilePayload | None) -> SearchPreferencesPayload:
    if profile is None:
        return SearchPreferencesPayload(result_limit=DEFAULT_RESULT_LIMIT)

    target_titles = _seed_titles(profile)
    target_responsibilities = _seed_responsibilities(profile)
    locations = _clean_items([profile.location or ""])
    include_keywords = _clean_items(profile.skills[:10])
    return SearchPreferencesPayload(
        target_titles=target_titles,
        target_responsibilities=target_responsibilities,
        locations=locations,
        workplace_modes=[],
        include_keywords=include_keywords,
        exclude_keywords=[],
        companies_include=[],
        companies_exclude=[],
        result_limit=DEFAULT_RESULT_LIMIT,
    )


def normalize_search_preferences(
    payload: SearchPreferencesPayload | dict | None,
) -> SearchPreferencesPayload:
    if payload is None:
        return SearchPreferencesPayload(result_limit=DEFAULT_RESULT_LIMIT)
    normalized = (
        payload if isinstance(payload, SearchPreferencesPayload) else SearchPreferencesPayload.model_validate(payload)
    )
    return SearchPreferencesPayload(
        target_titles=_clean_items(normalized.target_titles),
        target_responsibilities=_clean_items(normalized.target_responsibilities),
        locations=_clean_items(normalized.locations),
        workplace_modes=list(dict.fromkeys(normalized.workplace_modes)),
        include_keywords=_clean_items(normalized.include_keywords),
        exclude_keywords=_clean_items(normalized.exclude_keywords),
        companies_include=_clean_items(normalized.companies_include),
        companies_exclude=_clean_items(normalized.companies_exclude),
        result_limit=normalized.result_limit,
    )


def _seed_titles(profile: CandidateProfilePayload) -> list[str]:
    titles: list[str] = []
    if profile.headline:
        titles.append(profile.headline)
        titles.extend(_TITLE_SPLIT_PATTERN.split(profile.headline))
    titles.extend(experience.title or "" for experience in profile.experiences[:6])
    return _clean_items(titles)[:6]


def _seed_responsibilities(profile: CandidateProfilePayload) -> list[str]:
    responsibilities: list[str] = []
    if profile.summary:
        responsibilities.extend(_SENTENCE_SPLIT_PATTERN.split(profile.summary))
    for experience in profile.experiences[:6]:
        responsibilities.extend(experience.highlights[:4])
    cleaned = [item for item in _clean_items(responsibilities) if len(item) >= 12]
    return cleaned[:8]


def _clean_items(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        candidate = " ".join(str(value).strip().split())
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(candidate)
    return cleaned
