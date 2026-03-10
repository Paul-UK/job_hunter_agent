from __future__ import annotations

from apps.api.app.schemas import CandidateProfilePayload, RankingResult


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
    company_context = (
        research.get("github_summary") or research.get("website_summary") or "the team mission"
    )
    profile_hook = ", ".join(profile.skills[:3]) or "technical breadth"
    return [
        {
            "question": "Why are you interested in this role?",
            "answer": (
                f"I am targeting roles where I can apply {top_skill} to practical outcomes. "
                f"{job.get('company')} stands out because it appears closely connected to "
                f"{company_context}."
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
    if research.get("website_summary"):
        company_hook = (
            f" Your public positioning especially resonated with me: {research['website_summary']}"
        )
    elif research.get("github_summary"):
        company_hook = (
            f" The engineering signals from GitHub also stood out: {research['github_summary']}"
        )
    return intro + profile_hook + company_hook
