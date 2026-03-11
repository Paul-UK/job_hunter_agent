from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

from apps.api.app.schemas import CandidateProfilePayload, RankingResult
from apps.api.app.services.drafting import build_application_draft
from apps.api.app.services.llm.base import DraftedAnswerSuggestion, LLMClient


def suggest_application_text(
    *,
    target: str,
    profile: CandidateProfilePayload,
    job: dict[str, Any],
    ranking: RankingResult,
    research: dict[str, Any],
    llm_client: LLMClient,
    question: str | None = None,
    current_text: str | None = None,
    supporting_answers: list[dict[str, str]] | None = None,
) -> DraftedAnswerSuggestion:
    deterministic_draft = build_application_draft(profile, job, ranking, research)
    normalized_current_text = (current_text or "").strip()
    fallback_text = (
        normalized_current_text
        or _fallback_text(
            target=target,
            question=question,
            deterministic_draft=deterministic_draft,
            profile=profile,
        )
    )
    supporting_context = supporting_answers or deterministic_draft["screening_answers"]

    if llm_client.is_enabled():
        suggestion = llm_client.draft_application_material(
            material_type=target,
            question=question,
            current_text=normalized_current_text or fallback_text,
            profile=_profile_context(profile),
            job=_job_context(job),
            research=_research_context(research),
            supporting_answers=supporting_context,
        )
        if suggestion and suggestion.answer.strip():
            return DraftedAnswerSuggestion(
                answer=suggestion.answer.strip(),
                confidence=suggestion.confidence,
                reasoning=suggestion.reasoning or "LLM drafted grounded application text.",
            )

    return DraftedAnswerSuggestion(
        answer=fallback_text,
        confidence=0.34 if fallback_text else 0.0,
        reasoning=(
            "Template fallback used because no AI draft was available."
            if fallback_text
            else "No grounded draft content was available."
        ),
    )


def _fallback_text(
    *,
    target: str,
    question: str | None,
    deterministic_draft: dict[str, Any],
    profile: CandidateProfilePayload,
) -> str:
    if target == "cover_note":
        return str(deterministic_draft.get("cover_note") or "")

    screening_answers = deterministic_draft.get("screening_answers") or []
    if question:
        best_answer = None
        best_score = 0.0
        for screening_answer in screening_answers:
            candidate_question = str(screening_answer.get("question") or "")
            candidate_answer = str(screening_answer.get("answer") or "")
            score = fuzz.token_set_ratio(question, candidate_question)
            if score > best_score and candidate_answer.strip():
                best_score = score
                best_answer = candidate_answer.strip()
        if best_score >= 68 and best_answer:
            return best_answer

        lowered_question = question.lower()
        if "why" in lowered_question and deterministic_draft.get("cover_note"):
            return str(deterministic_draft["cover_note"])
        if "interview" in lowered_question and deterministic_draft.get("tailored_summary"):
            return str(deterministic_draft["tailored_summary"])

    return (profile.summary or deterministic_draft.get("tailored_summary") or "").strip()


def _profile_context(profile: CandidateProfilePayload) -> dict[str, Any]:
    return {
        "full_name": profile.full_name,
        "headline": profile.headline,
        "summary": profile.summary,
        "location": profile.location,
        "skills": profile.skills[:10],
        "achievements": profile.achievements[:5],
        "experiences": [
            {
                "company": experience.company,
                "title": experience.title,
                "duration": experience.duration,
                "highlights": experience.highlights[:3],
            }
            for experience in profile.experiences[:5]
        ],
        "education": [
            {
                "institution": education.institution,
                "degree": education.degree,
                "details": education.details,
            }
            for education in profile.education[:3]
        ],
        "links": profile.links,
    }


def _job_context(job: dict[str, Any]) -> dict[str, Any]:
    requirements = job.get("requirements")
    normalized_requirements = []
    if isinstance(requirements, list):
        normalized_requirements = [
            str(requirement).strip() for requirement in requirements if str(requirement).strip()
        ][:10]
    return {
        "company": job.get("company"),
        "title": job.get("title"),
        "location": job.get("location"),
        "employment_type": job.get("employment_type"),
        "description": job.get("description"),
        "requirements": normalized_requirements,
    }


def _research_context(research: dict[str, Any]) -> dict[str, Any]:
    return {
        "website_summary": research.get("website_summary"),
        "github_summary": research.get("github_summary"),
        "top_languages": (research.get("top_languages") or [])[:5],
        "website_url": research.get("website_url"),
    }
