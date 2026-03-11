from __future__ import annotations

from apps.api.app.schemas import CandidateProfilePayload, RankingResult
from apps.api.app.services.ai_drafting import suggest_application_text
from apps.api.app.services.drafting import build_application_draft
from apps.api.app.services.llm.base import DraftedAnswerSuggestion


class FakeLLMClient:
    def is_enabled(self) -> bool:
        return True

    def draft_application_material(self, **kwargs):
        target = kwargs["material_type"]
        if target == "cover_note":
            return DraftedAnswerSuggestion(
                answer="I am excited to bring hands-on Python and AI delivery experience to Anthropic.",
                confidence=0.88,
                reasoning="Grounded cover note rewrite.",
            )
        return DraftedAnswerSuggestion(
            answer=(
                "My background in Python, SQL, and AI operations maps well to this role and I can "
                "contribute quickly."
            ),
            confidence=0.83,
            reasoning="Grounded screening answer rewrite.",
        )


def test_build_application_draft_skips_ats_platform_copy_in_cover_note():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        skills=["Python", "SQL", "AWS", "GCP"],
    )
    ranking = RankingResult(
        score=78.0,
        matched_skills=["Python", "SQL", "AWS"],
        matched_signals=[],
        missing_signals=[],
        summary="Strong fit.",
    )
    research = {
        "website_summary": (
            "Greenhouse | Applicant tracking software & hiring platform. "
            "Greenhouse is more than your typical ATS recruiting software, "
            "powered by built-in AI recruiting tools to streamline sourcing."
        ),
        "website_url": "https://job-boards.greenhouse.io",
        "github_summary": "Public repositories show recent activity in Python, Shell.",
        "top_languages": ["Python", "Shell"],
    }

    draft = build_application_draft(
        profile,
        {"title": "Manager, Applied AI (Startups)", "company": "Anthropic"},
        ranking,
        research,
    )

    assert "Applicant tracking software" not in draft["cover_note"]
    assert "ATS recruiting software" not in draft["cover_note"]
    assert "public engineering work" in draft["cover_note"]


def test_build_application_draft_rephrases_company_summary_into_natural_hook():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        skills=["Python", "SQL", "AWS", "GCP"],
    )
    ranking = RankingResult(
        score=78.0,
        matched_skills=["Python", "SQL", "AWS"],
        matched_signals=[],
        missing_signals=[],
        summary="Strong fit.",
    )
    research = {
        "website_summary": (
            "Home \\\\ Anthropic. Anthropic is an AI safety and research company that's "
            "working to build reliable, interpretable, and steerable AI systems."
        ),
        "website_url": "https://anthropic.com",
    }

    draft = build_application_draft(
        profile,
        {"title": "Manager, Applied AI (Startups)", "company": "Anthropic"},
        ranking,
        research,
    )

    assert "highlights Anthropic is" not in draft["cover_note"]
    assert "the company is working to build reliable, interpretable, and steerable AI systems" in (
        draft["cover_note"]
    )


def test_suggest_application_text_prefers_llm_for_cover_note():
    profile = CandidateProfilePayload(
        full_name="Paul Example",
        summary="Support engineering leader focused on AI operations.",
        skills=["Python", "SQL", "AWS", "GCP"],
        achievements=[],
        experiences=[],
        education=[],
        links={},
    )
    ranking = RankingResult(
        score=78.0,
        matched_skills=["Python", "SQL", "AWS"],
        matched_signals=[],
        missing_signals=[],
        summary="Strong fit.",
    )
    suggestion = suggest_application_text(
        target="cover_note",
        profile=profile,
        job={
            "title": "Manager, Applied AI (Startups)",
            "company": "Anthropic",
            "description": "Help startups adopt AI systems.",
            "requirements": ["Python", "SQL"],
        },
        ranking=ranking,
        research={},
        llm_client=FakeLLMClient(),
        current_text="I am interested in this role.",
    )

    assert suggestion.answer == (
        "I am excited to bring hands-on Python and AI delivery experience to Anthropic."
    )
    assert suggestion.confidence == 0.88
