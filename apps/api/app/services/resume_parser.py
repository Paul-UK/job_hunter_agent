from __future__ import annotations

import re
from collections import defaultdict
from io import BytesIO

from docx import Document
from pypdf import PdfReader

from apps.api.app.schemas import CandidateProfilePayload, EducationItem, ExperienceItem

SECTION_ALIASES = {
    "summary": {"summary", "profile", "professional summary", "about"},
    "skills": {"skills", "competencies", "tech stack", "technologies"},
    "experience": {"experience", "work experience", "professional experience", "employment"},
    "education": {"education", "certifications", "training"},
    "achievements": {"achievements", "highlights", "key wins"},
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{8,}\d)")
LINK_RE = re.compile(r"https?://\S+")
SKILL_SPLIT_RE = re.compile(r"[,|/•]")


def extract_text_from_upload(filename: str, content: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"
    if suffix == "pdf":
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if suffix == "docx":
        document = Document(BytesIO(content))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    return content.decode("utf-8", errors="ignore").strip()


def parse_resume_text(text: str) -> CandidateProfilePayload:
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in normalized_text.split("\n")]
    non_empty_lines = [line for line in lines if line]
    sections = _extract_sections(lines)

    full_name = _guess_name(non_empty_lines)
    email = _first_match(EMAIL_RE, normalized_text)
    phone = _first_match(PHONE_RE, normalized_text)
    links = _extract_links(normalized_text)

    summary = _join_sentence_sections(sections.get("summary", []))
    headline = _guess_headline(non_empty_lines, full_name, summary)
    skills = _extract_skills(sections, normalized_text)
    experiences = _extract_experiences(sections.get("experience", []))
    education = _extract_education(sections.get("education", []))
    achievements = _extract_achievements(sections, experiences)
    location = _guess_location(non_empty_lines, email, phone)

    return CandidateProfilePayload(
        full_name=full_name,
        headline=headline,
        email=email,
        phone=phone,
        location=location,
        summary=summary,
        skills=skills,
        achievements=achievements,
        experiences=experiences,
        education=education,
        links=links,
    )


def _extract_sections(lines: list[str]) -> dict[str, list[str]]:
    detected_sections: dict[str, list[str]] = defaultdict(list)
    current_section = "summary"
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            detected_sections[current_section].append("")
            continue
        normalized = re.sub(r"[:\-]+$", "", line).strip().lower()
        matched_section = next(
            (canonical for canonical, aliases in SECTION_ALIASES.items() if normalized in aliases),
            None,
        )
        if matched_section:
            current_section = matched_section
            continue
        detected_sections[current_section].append(line)
    return dict(detected_sections)


def _guess_name(lines: list[str]) -> str | None:
    for line in lines[:4]:
        words = line.split()
        if 1 < len(words) <= 4 and "@" not in line and not any(char.isdigit() for char in line):
            return line.title() if line.isupper() else line
    return None


def _guess_headline(lines: list[str], full_name: str | None, summary: str | None) -> str | None:
    for line in lines[:8]:
        if line == full_name:
            continue
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            continue
        if len(line.split()) >= 3 and len(line) <= 120:
            return line
    if summary:
        return summary.split(".")[0][:120]
    return None


def _guess_location(lines: list[str], email: str | None, phone: str | None) -> str | None:
    for line in lines[:8]:
        if email and email in line:
            continue
        if phone and phone in line:
            continue
        if any(
            token in line.lower() for token in {"remote", "france", "paris", "london", "new york"}
        ):
            return line
    return None


def _extract_links(text: str) -> dict[str, str]:
    links: dict[str, str] = {}
    for url in LINK_RE.findall(text):
        if "linkedin.com" in url:
            links["linkedin"] = url.rstrip(".,)")
        elif "github.com" in url:
            links["github"] = url.rstrip(".,)")
        elif "http" in url and "portfolio" not in links:
            links["portfolio"] = url.rstrip(".,)")
    return links


def _extract_skills(sections: dict[str, list[str]], text: str) -> list[str]:
    raw_skills = sections.get("skills", [])
    if not raw_skills:
        raw_skills = re.findall(
            r"\b(?:python|sql|tensorflow|pytorch|react|typescript|fastapi|aws|gcp|kubernetes|docker|llm|nlp)\b",
            text,
            flags=re.IGNORECASE,
        )
    skills: list[str] = []
    for line in raw_skills:
        for part in SKILL_SPLIT_RE.split(line):
            cleaned = part.strip(" -").strip()
            if cleaned and len(cleaned) > 1:
                skills.append(cleaned)
    return _dedupe_preserve_case(skills)


def _extract_experiences(section_lines: list[str]) -> list[ExperienceItem]:
    entries: list[ExperienceItem] = []
    current_entry: ExperienceItem | None = None
    for line in section_lines:
        if not line:
            current_entry = None
            continue
        if line.startswith(("-", "•", "*")) and current_entry:
            current_entry.highlights.append(line.lstrip("-•* ").strip())
            continue
        if current_entry and not current_entry.highlights and current_entry.duration is None:
            current_entry.duration = line
            continue
        company, title, duration = _split_experience_line(line)
        current_entry = ExperienceItem(
            company=company, title=title, duration=duration, highlights=[]
        )
        entries.append(current_entry)
    return entries


def _split_experience_line(line: str) -> tuple[str, str | None, str | None]:
    duration = None
    duration_match = re.search(
        r"(\b20\d{2}\b.*|\b19\d{2}\b.*|present|current)", line, flags=re.IGNORECASE
    )
    working_line = line
    if duration_match:
        duration = duration_match.group(1).strip(" -|")
        working_line = line[: duration_match.start()].strip(" -|")
    if " at " in working_line.lower():
        title, company = re.split(r"\bat\b", working_line, maxsplit=1, flags=re.IGNORECASE)
        return company.strip(" -|"), title.strip(" -|"), duration
    if "|" in working_line:
        left, right = [part.strip() for part in working_line.split("|", 1)]
        return left, right, duration
    if " - " in working_line:
        left, right = [part.strip() for part in working_line.split(" - ", 1)]
        return left, right, duration
    return working_line, None, duration


def _extract_education(section_lines: list[str]) -> list[EducationItem]:
    results: list[EducationItem] = []
    for line in section_lines:
        if not line:
            continue
        if "|" in line:
            institution, degree = [part.strip() for part in line.split("|", 1)]
            results.append(EducationItem(institution=institution, degree=degree))
            continue
        if " - " in line:
            institution, degree = [part.strip() for part in line.split(" - ", 1)]
            results.append(EducationItem(institution=institution, degree=degree))
            continue
        results.append(EducationItem(institution=line))
    return results


def _extract_achievements(
    sections: dict[str, list[str]], experiences: list[ExperienceItem]
) -> list[str]:
    achievement_lines = [
        line.lstrip("-•* ").strip()
        for line in sections.get("achievements", [])
        if line and line.startswith(("-", "•", "*"))
    ]
    if achievement_lines:
        return _dedupe_preserve_case(achievement_lines)
    derived = [highlight for experience in experiences for highlight in experience.highlights]
    return _dedupe_preserve_case(derived[:8])


def _join_sentence_sections(lines: list[str]) -> str | None:
    text = " ".join(part.strip() for part in lines if part.strip())
    return text or None


def _dedupe_preserve_case(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1 if pattern.groups else 0).strip()
