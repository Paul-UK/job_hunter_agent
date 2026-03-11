from __future__ import annotations

from apps.api.app.services.company_research import (
    is_unhelpful_research_text,
    research_needs_refresh,
    summarize_company_website,
)


def test_summarize_company_website_ignores_greenhouse_job_board_host():
    research = summarize_company_website(
        "https://job-boards.greenhouse.io/anthropic/jobs/5142110008"
    )

    assert research == {"url": None, "summary": None}


def test_research_needs_refresh_for_ats_marketing_copy():
    research = {
        "website_summary": (
            "Greenhouse | Applicant tracking software & hiring platform. "
            "Greenhouse is more than your typical ATS recruiting software."
        ),
        "website_url": "https://job-boards.greenhouse.io",
    }

    assert research_needs_refresh(research) is True
    assert is_unhelpful_research_text(research["website_summary"]) is True
