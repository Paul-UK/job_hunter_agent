from __future__ import annotations

import re

from apps.api.app.schemas import CandidateProfilePayload, RankingResult
from apps.api.app.services.company_research import is_unhelpful_research_text


def build_application_draft(
    profile: CandidateProfilePayload,
    job: dict,
    ranking: RankingResult,
    research: dict,
) -> dict:
    resume_bullets = _build_resume_bullets(profile, ranking, research)
    screening_answers = _build_screening_answers(profile, job, ranking, research)
    cover_note = _build_cover_note(profile, job, research)
    top_matches = ", ".join(ranking.matched_skills[:3]) or "transferable experience"
    summary = (
        f"{profile.full_name or 'Candidate'} aligns with {job.get('title')} "
        f"at {job.get('company')} through {top_matches}."
    )
    return {
        "tailored_summary": summary,
        "cover_note": cover_note,
        "resume_bullets": resume_bullets,
        "screening_answers": screening_answers,
    }


def _build_resume_bullets(
    profile: CandidateProfilePayload,
    ranking: RankingResult,
    research: dict,
) -> list[str]:
    bullets = []
    if profile.summary:
        bullets.append(profile.summary)
    for achievement in profile.achievements[:2]:
        bullets.append(f"Relevant impact: {achievement}")
    if research.get("top_languages"):
        bullets.append(
            "Company stack alignment: strong overlap with "
            + ", ".join(research["top_languages"][:3])
            + "."
        )
    if ranking.matched_skills:
        bullets.append("Matched skills: " + ", ".join(ranking.matched_skills[:5]))
    return bullets[:4]


def _build_screening_answers(
    profile: CandidateProfilePayload,
    job: dict,
    ranking: RankingResult,
    research: dict,
) -> list[dict[str, str]]:
    top_skill = (
        ranking.matched_skills[0] if ranking.matched_skills else "your most relevant experience"
    )
    profile_hook = ", ".join(profile.skills[:3]) or "technical breadth"
    company_context = _research_context_phrase(research)
    interest_reason = (
        f"{job.get('company')} stands out because {company_context}."
        if company_context
        else f"{job.get('company')} stands out because the role lines up closely with my background."
    )
    return [
        {
            "question": "Why are you interested in this role?",
            "answer": (
                f"I am targeting roles where I can apply {top_skill} to practical outcomes. "
                f"{interest_reason}"
            ),
        },
        {
            "question": "Why should we interview you?",
            "answer": (
                f"My background combines {profile_hook} with delivery "
                f"experience that maps well to the responsibilities "
                f"in this {job.get('title')} role."
            ),
        },
    ]


def _build_cover_note(profile: CandidateProfilePayload, job: dict, research: dict) -> str:
    intro = f"I am excited to apply for the {job.get('title')} role at {job.get('company')}."
    profile_hook = (
        f" My background spans {', '.join(profile.skills[:4])}."
        if profile.skills
        else " My profile combines practical execution with adaptability."
    )
    company_hook = ""
    company_context = _research_context_phrase(research)
    if company_context:
        company_hook = f" I was also drawn to the role because {company_context}."
    return intro + profile_hook + company_hook


def _research_context_phrase(research: dict) -> str | None:
    website_summary = _clean_research_summary(research.get("website_summary"))
    if website_summary:
        return _extract_company_focus_phrase(website_summary) or (
            f"your public company narrative highlights {website_summary}"
        )

    org_description = _clean_research_summary(research.get("org_description"))
    if org_description:
        return f"the public company description emphasizes {org_description}"

    top_languages = [language for language in (research.get("top_languages") or []) if language]
    if top_languages:
        return f"the public engineering work shows recent activity in {', '.join(top_languages[:3])}"

    github_summary = _clean_research_summary(research.get("github_summary"))
    if github_summary:
        return github_summary[0].lower() + github_summary[1:] if github_summary else github_summary

    return None


def _clean_research_summary(value: str | None) -> str | None:
    if not value or is_unhelpful_research_text(value):
        return None

    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return None

    parts = [part.strip() for part in cleaned.split(".") if part.strip()]
    if len(parts) > 1 and len(parts[0].split()) <= 6:
        cleaned = parts[1]

    cleaned = cleaned.rstrip(".")
    if len(cleaned) > 180:
        cleaned = cleaned[:177].rsplit(" ", 1)[0] + "..."
    return cleaned or None


def _extract_company_focus_phrase(summary: str) -> str | None:
    cleaned_summary = summary.strip().rstrip(".")
    lowered_summary = cleaned_summary.lower()

    working_to_index = lowered_summary.find("working to ")
    if working_to_index >= 0:
        return f"the company is {cleaned_summary[working_to_index:]}"

    match = re.match(r"^[A-Z][A-Za-z0-9&' -]+ is (.+)$", cleaned_summary)
    if match:
        return f"the company is {match.group(1)}"

    for verb in ["builds", "develops", "creates", "focuses on"]:
        verb_index = lowered_summary.find(f"{verb} ")
        if verb_index >= 0:
            return f"the company {cleaned_summary[verb_index:]}"

    return None
