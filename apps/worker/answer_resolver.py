from __future__ import annotations

from rapidfuzz import fuzz

from apps.api.app.schemas import WorkerFieldState, WorkerPreviewSummary, WorkerRunRequest
from apps.api.app.services.llm.base import LLMClient


def resolve_fields(
    request: WorkerRunRequest, fields: list[WorkerFieldState], llm_client: LLMClient
) -> list[WorkerFieldState]:
    override_lookup = {
        override.field_id: override.value.strip()
        for override in request.answer_overrides
        if override.value.strip()
    }
    known_answers = _known_answers(request)
    resolved_fields: list[WorkerFieldState] = []

    for field in fields:
        field_value = override_lookup.get(field.field_id)
        if field_value:
            resolved_fields.append(
                field.model_copy(
                    update={
                        "answer_value": field_value,
                        "answer_source": "user_override",
                        "answer_confidence": 1.0,
                        "requires_review": False,
                        "review_reason": None,
                    }
                )
            )
            continue

        if field.canonical_key and known_answers.get(field.canonical_key):
            resolved_fields.append(
                field.model_copy(
                    update={
                        "answer_value": known_answers[field.canonical_key],
                        "answer_source": _answer_source(field.canonical_key),
                        "answer_confidence": 0.96,
                        "requires_review": False,
                        "review_reason": None,
                    }
                )
            )
            continue

        if field.canonical_key == "custom_question":
            resolved_fields.append(_resolve_custom_question(field, request, llm_client))
            continue

        if field.required:
            resolved_fields.append(
                field.model_copy(
                    update={
                        "requires_review": True,
                        "review_reason": "Required field still needs an answer.",
                    }
                )
            )
            continue

        resolved_fields.append(field)

    return resolved_fields


def build_preview_summary(fields: list[WorkerFieldState]) -> WorkerPreviewSummary:
    required_fields = [field for field in fields if field.required]
    review_fields = [field for field in fields if field.requires_review]
    unresolved_required = [
        field for field in required_fields if field.requires_review or not (field.answer_value or "").strip()
    ]
    autofill_ready = [
        field
        for field in fields
        if (field.answer_value or "").strip() and not field.requires_review and field.canonical_key
    ]
    llm_suggestions = [field for field in fields if field.answer_source == "gemini"]

    return WorkerPreviewSummary(
        total_fields=len(fields),
        autofill_ready_count=len(autofill_ready),
        required_count=len(required_fields),
        review_required_count=len(review_fields),
        unresolved_required_count=len(unresolved_required),
        llm_suggestions_count=len(llm_suggestions),
    )


def _resolve_custom_question(
    field: WorkerFieldState, request: WorkerRunRequest, llm_client: LLMClient
) -> WorkerFieldState:
    matched_screening_answer = _matching_screening_answer(field.question_text, request)
    if matched_screening_answer:
        return field.model_copy(
            update={
                "answer_value": matched_screening_answer,
                "answer_source": "screening_answer",
                "answer_confidence": 0.78,
                "requires_review": True,
                "review_reason": "Review drafted answer before submission.",
            }
        )

    llm_suggestion = llm_client.draft_long_form_answer(
        question=field.question_text or field.label,
        company=request.job.company,
        job_title=request.job.title,
        profile_summary=request.profile.summary or "",
        profile_skills=request.profile.skills,
        cover_note=request.draft.cover_note,
        screening_answers=[answer.model_dump(mode="json") for answer in request.draft.screening_answers],
    )
    if llm_suggestion:
        return field.model_copy(
            update={
                "answer_value": llm_suggestion.answer,
                "answer_source": "gemini",
                "answer_confidence": llm_suggestion.confidence,
                "requires_review": True,
                "review_reason": llm_suggestion.reasoning or "Gemini suggested an answer that needs review.",
            }
        )

    fallback_answer = _fallback_custom_answer(field, request)
    if fallback_answer:
        return field.model_copy(
            update={
                "answer_value": fallback_answer,
                "answer_source": "draft_context",
                "answer_confidence": 0.52,
                "requires_review": True,
                "review_reason": "Suggested from draft context; review before submission.",
            }
        )

    if field.required:
        return field.model_copy(
            update={
                "requires_review": True,
                "review_reason": "Required custom question needs an answer.",
            }
        )
    return field


def _known_answers(request: WorkerRunRequest) -> dict[str, str]:
    links = request.profile.links or {}
    full_name = (request.profile.full_name or "").strip()
    first_name, last_name = _split_name(full_name)
    return {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "email": (request.profile.email or "").strip(),
        "phone": (request.profile.phone or "").strip(),
        "location": (request.profile.location or "").strip(),
        "linkedin": links.get("linkedin", "").strip(),
        "github": links.get("github", "").strip(),
        "portfolio": links.get("portfolio", "").strip(),
        "website": links.get("website", "").strip(),
        "resume_path": links.get("resume_path", "").strip(),
        "cover_note": (request.draft.cover_note or "").strip(),
    }


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.split() if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _matching_screening_answer(question_text: str, request: WorkerRunRequest) -> str | None:
    normalized_question = question_text.strip()
    if not normalized_question:
        return None

    best_score = 0
    best_answer = None
    for screening_answer in request.draft.screening_answers:
        score = fuzz.token_set_ratio(normalized_question, screening_answer.question)
        if score > best_score:
            best_score = score
            best_answer = screening_answer.answer

    if best_score >= 68 and best_answer:
        return best_answer
    return None


def _fallback_custom_answer(field: WorkerFieldState, request: WorkerRunRequest) -> str | None:
    prompt = (field.question_text or field.label).lower()
    if "why" in prompt and request.draft.cover_note:
        return request.draft.cover_note
    if "additional" in prompt and request.profile.summary:
        return request.profile.summary
    return None


def _answer_source(canonical_key: str) -> str:
    if canonical_key == "cover_note":
        return "draft"
    if canonical_key == "resume_path":
        return "profile_link"
    return "profile"
