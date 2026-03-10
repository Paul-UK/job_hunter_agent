from __future__ import annotations

import json
from typing import Any

import httpx

from apps.api.app.services.llm.base import (
    DraftedAnswerSuggestion,
    FieldClassificationSuggestion,
)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def is_enabled(self) -> bool:
        return bool(self.api_key)

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
        prompt = {
            "task": "Classify a job application field into a canonical key.",
            "platform": platform,
            "allowed_keys": [
                "first_name",
                "last_name",
                "full_name",
                "email",
                "phone",
                "location",
                "linkedin",
                "github",
                "portfolio",
                "website",
                "resume_path",
                "cover_note",
                "work_authorization",
                "visa_sponsorship",
                "salary_expectation",
                "start_date",
                "custom_question",
                "unknown",
            ],
            "field": {
                "label": label,
                "question_text": question_text,
                "field_type": field_type,
                "html_name": html_name,
                "html_id": html_id,
                "options": options,
            },
            "response_shape": {
                "canonical_key": "string",
                "confidence": "number 0-1",
                "reasoning": "short string",
            },
        }
        payload = self._generate_json(prompt)
        if not payload:
            return None
        canonical_key = str(payload.get("canonical_key") or "").strip() or None
        if canonical_key == "unknown":
            canonical_key = None
        confidence = _as_confidence(payload.get("confidence"))
        reasoning = str(payload.get("reasoning") or "Gemini classification").strip()
        if confidence <= 0:
            return None
        return FieldClassificationSuggestion(
            canonical_key=canonical_key,
            confidence=confidence,
            reasoning=reasoning,
        )

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
        prompt = {
            "task": "Draft a concise job application answer in first person.",
            "constraints": [
                "Be honest and specific.",
                "Keep the answer under 140 words.",
                "Do not invent experience not present in the context.",
                "Return JSON only.",
            ],
            "question": question,
            "company": company,
            "job_title": job_title,
            "candidate_context": {
                "profile_summary": profile_summary,
                "skills": profile_skills[:8],
                "cover_note": cover_note,
                "screening_answers": screening_answers[:4],
            },
            "response_shape": {
                "answer": "string",
                "confidence": "number 0-1",
                "reasoning": "short string",
            },
        }
        payload = self._generate_json(prompt)
        if not payload:
            return None
        answer = str(payload.get("answer") or "").strip()
        if not answer:
            return None
        return DraftedAnswerSuggestion(
            answer=answer,
            confidence=_as_confidence(payload.get("confidence")),
            reasoning=str(payload.get("reasoning") or "Gemini drafted answer").strip(),
        )

    def _generate_json(self, prompt: dict[str, Any]) -> dict[str, Any] | None:
        url = f"{GEMINI_BASE_URL}/{self.model}:generateContent"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Return valid JSON only.\n"
                                + json.dumps(prompt, ensure_ascii=True, indent=2)
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, params={"key": self.api_key}, json=payload)
                response.raise_for_status()
        except httpx.HTTPError:
            return None

        data = response.json()
        text_parts = []
        for candidate in data.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if isinstance(part, dict) and part.get("text"):
                    text_parts.append(part["text"])

        if not text_parts:
            return None

        try:
            return json.loads(text_parts[0])
        except json.JSONDecodeError:
            return None


def _as_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))
