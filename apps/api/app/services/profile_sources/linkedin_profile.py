from __future__ import annotations

from bs4 import BeautifulSoup

from apps.api.app.schemas import CandidateProfilePayload
from apps.api.app.services.resume_parser import parse_resume_text


def parse_linkedin_source(
    raw_content: str, is_html: bool = False
) -> tuple[CandidateProfilePayload, dict[str, float]]:
    cleaned_text = _html_to_text(raw_content) if is_html else raw_content
    parsed = parse_resume_text(cleaned_text)

    confidence = {
        "full_name": 0.85 if parsed.full_name else 0.0,
        "headline": 0.9 if parsed.headline else 0.0,
        "skills": 0.75 if parsed.skills else 0.0,
        "experiences": 0.8 if parsed.experiences else 0.0,
        "education": 0.7 if parsed.education else 0.0,
    }
    return parsed, confidence


def merge_profile_payloads(
    cv_payload: CandidateProfilePayload | None,
    linkedin_payload: CandidateProfilePayload | None,
) -> tuple[CandidateProfilePayload, dict[str, str]]:
    if cv_payload is None and linkedin_payload is None:
        return CandidateProfilePayload(), {}
    if cv_payload is None:
        return linkedin_payload or CandidateProfilePayload(), _source_map("linkedin")
    if linkedin_payload is None:
        return cv_payload, _source_map("cv")

    merged_data = cv_payload.model_dump()
    linkedin_data = linkedin_payload.model_dump()
    field_sources: dict[str, str] = {}

    for field_name, cv_value in merged_data.items():
        linkedin_value = linkedin_data.get(field_name)
        if _is_empty(cv_value) and not _is_empty(linkedin_value):
            merged_data[field_name] = linkedin_value
            field_sources[field_name] = "linkedin"
        else:
            field_sources[field_name] = "cv"

    if merged_data.get("skills"):
        merged_data["skills"] = _merge_lists(cv_payload.skills, linkedin_payload.skills)
        field_sources["skills"] = "cv+linkedin"
    if merged_data.get("achievements"):
        merged_data["achievements"] = _merge_lists(
            cv_payload.achievements, linkedin_payload.achievements
        )
        field_sources["achievements"] = "cv+linkedin"
    if merged_data.get("experiences"):
        merged_data["experiences"] = _merge_models(
            cv_payload.experiences, linkedin_payload.experiences
        )
        field_sources["experiences"] = "cv+linkedin"
    if merged_data.get("education"):
        merged_data["education"] = _merge_models(cv_payload.education, linkedin_payload.education)
        field_sources["education"] = "cv+linkedin"
    if merged_data.get("links") or linkedin_payload.links:
        merged_links = dict(linkedin_payload.links)
        merged_links.update(cv_payload.links)
        merged_data["links"] = merged_links
        field_sources["links"] = "cv+linkedin"

    return CandidateProfilePayload.model_validate(merged_data), field_sources


def _html_to_text(content: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


def _merge_lists(primary: list[str], secondary: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in [*primary, *secondary]:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    return merged


def _merge_models(primary: list, secondary: list) -> list:
    seen: set[str] = set()
    merged: list = []
    for item in [*primary, *secondary]:
        key = repr(item.model_dump())
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _source_map(source_name: str) -> dict[str, str]:
    return {
        "full_name": source_name,
        "headline": source_name,
        "email": source_name,
        "phone": source_name,
        "location": source_name,
        "summary": source_name,
        "skills": source_name,
        "achievements": source_name,
        "experiences": source_name,
        "education": source_name,
        "links": source_name,
    }


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False
