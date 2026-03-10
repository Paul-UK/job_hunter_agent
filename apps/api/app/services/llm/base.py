from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class FieldClassificationSuggestion:
    canonical_key: str | None
    confidence: float
    reasoning: str


@dataclass(slots=True)
class DraftedAnswerSuggestion:
    answer: str
    confidence: float
    reasoning: str


class LLMClient(Protocol):
    def is_enabled(self) -> bool: ...

    def classify_field(
        self,
        *,
        platform: str,
        label: str,
        question_text: str,
        field_type: str,
        html_name: str | None,
        html_id: str | None,
        options: list[dict[str, str]],
    ) -> FieldClassificationSuggestion | None: ...

    def draft_long_form_answer(
        self,
        *,
        question: str,
        company: str,
        job_title: str,
        profile_summary: str,
        profile_skills: list[str],
        cover_note: str,
        screening_answers: list[dict[str, str]],
    ) -> DraftedAnswerSuggestion | None: ...


class DisabledLLMClient:
    def is_enabled(self) -> bool:
        return False

    def classify_field(
        self,
        *,
        platform: str,
        label: str,
        question_text: str,
        field_type: str,
        html_name: str | None,
        html_id: str | None,
        options: list[dict[str, str]],
    ) -> FieldClassificationSuggestion | None:
        return None

    def draft_long_form_answer(
        self,
        *,
        question: str,
        company: str,
        job_title: str,
        profile_summary: str,
        profile_skills: list[str],
        cover_note: str,
        screening_answers: list[dict[str, str]],
    ) -> DraftedAnswerSuggestion | None:
        return None
