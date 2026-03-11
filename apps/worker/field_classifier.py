from __future__ import annotations

import re

from apps.api.app.schemas import WorkerFieldState
from apps.api.app.services.llm.base import LLMClient

CANONICAL_LABELS = {
    "first_name": "First name",
    "last_name": "Last name",
    "full_name": "Full name",
    "email": "Email",
    "phone": "Phone",
    "phone_country_code": "Phone country code",
    "location": "Location",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "website": "Website",
    "portfolio": "Portfolio",
    "resume_path": "Resume",
    "cover_note": "Cover note",
    "work_authorization": "Work authorization",
    "visa_sponsorship": "Visa sponsorship",
    "salary_expectation": "Salary expectation",
    "start_date": "Start date",
    "custom_question": "Custom question",
}

HEURISTIC_PATTERNS: list[tuple[str, tuple[str, ...], float]] = [
    ("first_name", (r"\bfirst name\b", r"\bgiven name\b"), 0.99),
    ("last_name", (r"\blast name\b", r"\bsurname\b", r"\bfamily name\b"), 0.99),
    ("full_name", (r"\bfull name\b", r"\byour name\b"), 0.96),
    ("email", (r"\be[- ]?mail\b",), 0.99),
    ("phone", (r"\bphone\b", r"\bmobile\b", r"\btelephone\b", r"\bcell\b"), 0.98),
    (
        "linkedin",
        (r"\blinkedin\b", r"\blinked in\b"),
        0.99,
    ),
    ("github", (r"\bgithub\b",), 0.99),
    ("portfolio", (r"\bportfolio\b",), 0.98),
    ("website", (r"\bwebsite\b", r"\bpersonal site\b"), 0.9),
    (
        "resume_path",
        (r"\bresume\b", r"\bcv\b", r"\bupload\b"),
        0.97,
    ),
    (
        "cover_note",
        (r"\bcover letter\b", r"\bcover note\b", r"\badditional information\b", r"\bcomments\b"),
        0.84,
    ),
    (
        "location",
        (
            r"\blocation\b",
            r"\baddress\b",
            r"\bcity\b",
            r"\bfrom which you plan on working\b",
            r"\bwhere do you plan on working\b",
        ),
        0.9,
    ),
    (
        "work_authorization",
        (r"\bauthori[sz]ed to work\b", r"\bwork authori[sz]ation\b", r"\bwork permit\b"),
        0.88,
    ),
    (
        "visa_sponsorship",
        (r"\bvisa sponsorship\b", r"\brequire sponsorship\b", r"\bsponsorship\b"),
        0.88,
    ),
    (
        "salary_expectation",
        (r"\bsalary\b", r"\bcompensation\b", r"\bexpected pay\b", r"\bbase pay\b"),
        0.86,
    ),
    (
        "start_date",
        (
            r"\bstart date\b",
            r"\bearliest .*start\b",
            r"\bwhen can you start\b",
            r"\bnotice period\b",
        ),
        0.82,
    ),
]


def classify_fields(
    fields: list[WorkerFieldState], platform: str, llm_client: LLMClient
) -> list[WorkerFieldState]:
    return [classify_field(field, platform, llm_client) for field in fields]


def classify_field(field: WorkerFieldState, platform: str, llm_client: LLMClient) -> WorkerFieldState:
    heuristic = _heuristic_classification(field)
    if heuristic is not None:
        canonical_key, confidence, reasoning = heuristic
        return field.model_copy(
            update={
                "canonical_key": canonical_key,
                "canonical_label": CANONICAL_LABELS.get(canonical_key),
                "classification_confidence": confidence,
                "classification_source": "heuristic",
                "classification_reasoning": reasoning,
            }
        )

    if llm_client.is_enabled():
        suggestion = llm_client.classify_field(
            platform=platform,
            label=field.label,
            question_text=field.question_text,
            field_type=field.field_type,
            html_name=field.html_name,
            html_id=field.html_id,
            options=[option.model_dump(mode="json") for option in field.options],
        )
        if suggestion and suggestion.confidence >= 0.6:
            canonical_key = suggestion.canonical_key or "custom_question"
            return field.model_copy(
                update={
                    "canonical_key": canonical_key,
                    "canonical_label": CANONICAL_LABELS.get(canonical_key),
                    "classification_confidence": suggestion.confidence,
                    "classification_source": "gemini",
                    "classification_reasoning": suggestion.reasoning,
                }
            )

    if _looks_like_custom_question(field):
        return field.model_copy(
            update={
                "canonical_key": "custom_question",
                "canonical_label": CANONICAL_LABELS["custom_question"],
                "classification_confidence": 0.55,
                "classification_source": "fallback",
                "classification_reasoning": "Treating unknown visible application field as a custom question.",
            }
        )

    return field.model_copy(
        update={
            "classification_confidence": 0.0,
            "classification_source": "unclassified",
            "classification_reasoning": "No reliable canonical mapping found.",
        }
    )


def _heuristic_classification(field: WorkerFieldState) -> tuple[str, float, str] | None:
    if _looks_like_phone_country_code(field):
        return "phone_country_code", 0.93, "Matched phone country code heuristic."

    text = _field_text(field)
    for canonical_key, patterns, confidence in HEURISTIC_PATTERNS:
        if any(re.search(pattern, text) for pattern in patterns):
            return canonical_key, confidence, f"Matched {canonical_key} heuristic."

    if field.field_type == "file":
        return "resume_path", 0.75, "Defaulted visible file input to resume upload."

    return None


def _looks_like_phone_country_code(field: WorkerFieldState) -> bool:
    if field.field_type != "select" or len(field.options) < 20:
        return False

    text = _field_text(field)
    has_country_signal = bool(re.search(r"\bcountry\b|\bcountry code\b|\bdial code\b", text))
    has_dial_code_options = sum(
        1
        for option in field.options[:30]
        if re.search(r"\+\d{1,4}\b", option.label) or re.search(r"\+\d{1,4}\b", option.value)
    )
    return has_country_signal and has_dial_code_options >= 5


def _looks_like_custom_question(field: WorkerFieldState) -> bool:
    if field.field_type in {"textarea", "select", "radio", "checkbox"}:
        return True
    if field.required:
        return True
    text = _field_text(field)
    return bool(re.search(r"\b(question|why|describe|explain|additional)\b", text))


def _field_text(field: WorkerFieldState) -> str:
    return " ".join(
        _normalize(part)
        for part in [
            field.label,
            field.question_text,
            field.placeholder,
            field.html_name or "",
            field.html_id or "",
            field.canonical_label or "",
            " ".join(option.label for option in field.options),
        ]
        if part
    ).strip()


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
