from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from apps.api.app.config import settings
from apps.api.app.schemas import WorkerActionPayload, WorkerFieldState, WorkerRunRequest
from apps.api.app.services.llm import get_llm_client
from apps.worker.answer_resolver import build_preview_summary, resolve_fields
from apps.worker.field_classifier import classify_fields
from apps.worker.form_extractor import extract_form_fields
from apps.worker.platform_adapters import (
    detect_platform,
    get_selector_fallbacks,
    get_submit_hints,
)

SUBMISSION_CONFIRMATION_TEXT_PATTERNS = [
    re.compile(r"\bthank you for applying\b", re.IGNORECASE),
    re.compile(r"\bthanks for applying\b", re.IGNORECASE),
    re.compile(r"\byour application has been submitted\b", re.IGNORECASE),
    re.compile(r"\bapplication (?:has been )?submitted\b", re.IGNORECASE),
    re.compile(r"\bapplication received\b", re.IGNORECASE),
    re.compile(r"\bwe(?:'ve| have) received your application\b", re.IGNORECASE),
    re.compile(r"\bsubmission received\b", re.IGNORECASE),
]
SUBMISSION_CONFIRMATION_URL_PATTERNS = [
    re.compile(r"/(thank-you|thanks|submitted|submission|confirmation|complete)\b", re.IGNORECASE),
]
VALIDATION_ERROR_TEXT_PATTERNS = [
    re.compile(r"\bthis field is required\b", re.IGNORECASE),
    re.compile(r"\bplease (?:fill|complete|enter|select)\b", re.IGNORECASE),
    re.compile(r"\benter a valid\b", re.IGNORECASE),
    re.compile(r"\bmust be selected\b", re.IGNORECASE),
    re.compile(r"\bcan't be blank\b", re.IGNORECASE),
]
VERIFICATION_REQUIRED_TEXT_PATTERNS = [
    re.compile(r"\bverification code\b", re.IGNORECASE),
    re.compile(r"\bcheck your email\b", re.IGNORECASE),
    re.compile(r"\bconfirm your email\b", re.IGNORECASE),
    re.compile(r"\bverify your email\b", re.IGNORECASE),
    re.compile(r"\benter (?:the )?code\b", re.IGNORECASE),
    re.compile(r"\bone[- ]time code\b", re.IGNORECASE),
    re.compile(r"\bsecurity code\b", re.IGNORECASE),
]
VERIFICATION_FOLLOW_UP_FIELD_PATTERNS = [
    re.compile(r"\bverification\b", re.IGNORECASE),
    re.compile(r"\bconfirmation\b", re.IGNORECASE),
    re.compile(r"\bone[- ]?time\b", re.IGNORECASE),
    re.compile(r"\bsecurity\b", re.IGNORECASE),
    re.compile(r"\bpasscode\b", re.IGNORECASE),
    re.compile(r"\botp\b", re.IGNORECASE),
]
VERIFICATION_REVIEW_REASON = (
    "Verification code input appeared after submit. Enter the code from the ATS email checkpoint. "
    "Retries still start a fresh browser session."
)
SCREENSHOT_CAPTURE_STATUSES = {
    "failed",
    "submit_failed",
    "verification_required",
    "submit_clicked",
    "submitted",
}


@dataclass(frozen=True)
class SubmissionConfirmationResult:
    confirmed: bool
    outcome: Literal["confirmed", "invalid", "verification", "unconfirmed"]
    log: str


def run_worker(request: WorkerRunRequest) -> dict[str, Any]:
    logs: list[str] = []
    actions: list[dict[str, Any]] = []
    fields: list[WorkerFieldState] = []
    review_items: list[WorkerFieldState] = []
    screenshot_path: str | None = None
    status = "failed"
    preview_summary = build_preview_summary([])
    platform = detect_platform(str(request.target_url), request.platform)
    llm_client = get_llm_client()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            if request.fixture_html:
                page.set_content(request.fixture_html, wait_until="load")
                logs.append("Loaded fixture HTML for worker run.")
            else:
                page.goto(str(request.target_url), wait_until="domcontentloaded", timeout=30000)
                logs.append(f"Opened target page for {platform}.")

            try:
                page.wait_for_load_state("networkidle", timeout=2500)
            except PlaywrightTimeoutError:
                logs.append("Page stayed active after load; continued with semantic extraction.")

            extracted_fields = extract_form_fields(page)
            logs.append(f"Extracted {len(extracted_fields)} visible form fields.")

            classified_fields = classify_fields(extracted_fields, platform, llm_client)
            fields = resolve_fields(request, classified_fields, llm_client)
            review_items = [field for field in fields if field.requires_review]
            preview_summary = build_preview_summary(fields)
            actions = _build_actions(page, platform, fields, logs)

            blocking_review = any(field.required and field.requires_review for field in review_items)
            if blocking_review:
                status = "awaiting_answers"
                logs.append("Required questions still need review before autofill can proceed.")
            elif request.dry_run:
                status = "preview_ready"
                logs.append("Preview generated; no fields were submitted.")
            elif not request.confirm_submit:
                failed_actions = _apply_actions(page, actions, logs)
                status = "ready_for_submit"
                if failed_actions:
                    logs.append(
                        f"{len(failed_actions)} field action(s) could not be applied; review before submit."
                    )
                else:
                    logs.append("Filled high-confidence fields and paused before submit.")
            else:
                failed_actions = _apply_actions(page, actions, logs)
                if failed_actions:
                    status = "ready_for_submit"
                    logs.append(
                        f"{len(failed_actions)} field action(s) could not be applied; skipped final submit."
                    )
                else:
                    submit_selector = _first_actionable_selector(page, get_submit_hints(platform))
                    if submit_selector:
                        pre_submit_url = page.url
                        page.locator(submit_selector).first.click()
                        logs.append(f"Clicked submit using {submit_selector}.")
                        confirmation = _confirm_submission(
                            page,
                            initial_url=pre_submit_url,
                        )
                        if confirmation.confirmed:
                            status = "submitted"
                        elif confirmation.outcome == "invalid":
                            status = "submit_failed"
                        elif confirmation.outcome == "verification":
                            status = "verification_required"
                            verification_fields = _extract_post_submit_verification_fields(
                                page,
                                platform,
                                llm_client,
                                existing_fields=fields,
                                logs=logs,
                            )
                            if verification_fields:
                                fields = _merge_fields(fields, verification_fields)
                                review_items = [field for field in fields if field.requires_review]
                                preview_summary = build_preview_summary(fields)
                        else:
                            status = "submit_clicked"
                        logs.append(confirmation.log)
                    else:
                        status = "ready_for_submit"
                        logs.append(
                            "Submit button was not detected; left page ready for manual review."
                        )
        except PlaywrightTimeoutError:
            status = "failed"
            logs.append("Timed out while loading or interacting with the page.")
        except PlaywrightError as exc:
            status = "failed"
            logs.append(f"Browser automation failed: {exc}")
        finally:
            if _should_capture_screenshot(status):
                try:
                    screenshot_path = _save_screenshot(page, platform)
                except PlaywrightError as exc:
                    logs.append(f"Could not capture final screenshot: {exc}")
            browser.close()

    return {
        "application_draft_id": request.application_draft_id,
        "platform": platform,
        "target_url": str(request.target_url),
        "dry_run": request.dry_run,
        "status": status,
        "actions": actions,
        "logs": logs,
        "screenshot_path": screenshot_path,
        "fields": [field.model_dump(mode="json") for field in fields],
        "review_items": [field.model_dump(mode="json") for field in review_items],
        "preview_summary": preview_summary.model_dump(mode="json"),
        "profile_snapshot": request.profile.model_dump(mode="json"),
        "job_snapshot": request.job.model_dump(mode="json"),
        "draft_snapshot": request.draft.model_dump(mode="json"),
    }


def _build_actions(page, platform: str, fields: list[WorkerFieldState], logs: list[str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for field in fields:
        value = (field.answer_value or "").strip()
        if field.field_type == "file" and field.canonical_key != "resume_path":
            if value:
                logs.append(
                    f"Skipped unsupported file upload field '{field.label or field.field_id}'."
                )
            continue
        if not value or field.requires_review:
            continue

        if field.field_type in {"radio", "checkbox"}:
            option = _matching_option(field, value)
            option_selector = _resolve_option_selector(page, option) if option else None
            if option and option_selector:
                actions.append(
                    WorkerActionPayload(
                        field=field.canonical_key or field.label or field.field_id,
                        selector=option_selector,
                        value=option.value or option.label,
                        field_id=field.field_id,
                        mode="check" if field.input_type in {"radio", "checkbox"} else "click",
                        option_label=option.label,
                    ).model_dump(mode="json")
                )
                continue

        selector = _resolve_selector(page, platform, field)
        if not selector:
            logs.append(
                f"No actionable selector found for '{field.label or field.field_id}'."
            )
            continue

        option = _matching_option(field, value) if field.field_type == "select" else None
        mode = "fill"
        if field.field_type == "select":
            mode = "select" if field.input_type == "select" else "choose"
        elif _should_use_autocomplete(field):
            mode = "autocomplete"
        autocomplete_option_candidates = _react_select_option_candidates(field) if mode == "autocomplete" else []
        actions.append(
            WorkerActionPayload(
                field=field.canonical_key or field.label or field.field_id,
                selector=selector,
                value=value if field.canonical_key != "resume_path" else Path(value).name,
                field_id=field.field_id,
                mode=mode,
                option_label=option.label if option else value,
                option_selector=option.selector if option else None,
                option_selector_candidates=(
                    option.selector_candidates if option else autocomplete_option_candidates
                ),
            ).model_dump(mode="json")
        )
    return actions


def _extract_post_submit_verification_fields(
    page,
    platform: str,
    llm_client,
    *,
    existing_fields: list[WorkerFieldState],
    logs: list[str],
) -> list[WorkerFieldState]:
    post_submit_fields = extract_form_fields(page)
    existing_field_ids = {field.field_id for field in existing_fields}
    surfaced_fields: list[WorkerFieldState] = []
    seen_field_ids: set[str] = set()

    if post_submit_fields:
        logs.append(
            f"Extracted {len(post_submit_fields)} visible field(s) from the post-submit verification step."
        )
        classified_fields = classify_fields(post_submit_fields, platform, llm_client)
        for field in classified_fields:
            if field.field_id in seen_field_ids:
                continue
            if not _should_surface_verification_field(field, existing_field_ids):
                continue
            surfaced_fields.append(_mark_field_for_verification_review(field))
            seen_field_ids.add(field.field_id)

    if surfaced_fields:
        logs.append(f"Surfaced {len(surfaced_fields)} verification follow-up field(s).")
        return surfaced_fields

    prompt = _extract_verification_prompt(page)
    if not prompt:
        return []

    logs.append("Surfaced a verification code prompt from the post-submit page.")
    return [
        WorkerFieldState(
            field_id="post-submit-verification-code",
            label="Verification code",
            question_text=prompt,
            selector="[data-post-submit-verification-code]",
            field_type="text",
            input_type="text",
            required=True,
            canonical_key="verification_code",
            canonical_label="Verification code",
            classification_confidence=1.0,
            classification_source="post_submit",
            classification_reasoning="Detected a verification checkpoint after submit.",
            answer_value=None,
            answer_source=None,
            answer_confidence=0.0,
            requires_review=True,
            review_reason=VERIFICATION_REVIEW_REASON,
        )
    ]


def _should_surface_verification_field(
    field: WorkerFieldState, existing_field_ids: set[str]
) -> bool:
    if field.canonical_key == "verification_code" or _looks_like_verification_follow_up_field(field):
        return True
    return field.field_id not in existing_field_ids and field.required


def _looks_like_verification_follow_up_field(field: WorkerFieldState) -> bool:
    text = " ".join(
        part
        for part in [
            field.label,
            field.question_text,
            field.placeholder,
            field.html_name or "",
            field.html_id or "",
            field.canonical_label or "",
        ]
        if part
    ).strip()
    return bool(text) and _matches_any(VERIFICATION_FOLLOW_UP_FIELD_PATTERNS, text)


def _mark_field_for_verification_review(field: WorkerFieldState) -> WorkerFieldState:
    canonical_key = field.canonical_key or (
        "verification_code" if _looks_like_verification_follow_up_field(field) else None
    )
    canonical_label = field.canonical_label or (
        "Verification code" if canonical_key == "verification_code" else None
    )
    return field.model_copy(
        update={
            "canonical_key": canonical_key,
            "canonical_label": canonical_label,
            "answer_value": None,
            "answer_source": None,
            "answer_confidence": 0.0,
            "requires_review": True,
            "review_reason": VERIFICATION_REVIEW_REASON,
            "classification_source": field.classification_source or "post_submit",
            "classification_reasoning": field.classification_reasoning
            or "Detected a verification checkpoint after submit.",
        }
    )


def _extract_verification_prompt(page) -> str | None:
    state = _read_post_submit_state(page)
    combined_text = " ".join(
        segment
        for segment in [
            str(state.get("alert_text") or "").strip(),
            str(state.get("body_text") or "").strip(),
        ]
        if segment
    ).strip()
    if not combined_text or not _matches_any(VERIFICATION_REQUIRED_TEXT_PATTERNS, combined_text):
        return None

    for sentence in re.split(r"(?<=[.!?])\s+", combined_text):
        normalized_sentence = sentence.strip()
        if normalized_sentence and _matches_any(VERIFICATION_REQUIRED_TEXT_PATTERNS, normalized_sentence):
            return normalized_sentence[:220]
    return combined_text[:220]


def _merge_fields(
    existing_fields: list[WorkerFieldState], new_fields: list[WorkerFieldState]
) -> list[WorkerFieldState]:
    merged_fields = list(existing_fields)
    index_by_field_id = {field.field_id: index for index, field in enumerate(merged_fields)}
    for field in new_fields:
        existing_index = index_by_field_id.get(field.field_id)
        if existing_index is None:
            index_by_field_id[field.field_id] = len(merged_fields)
            merged_fields.append(field)
        else:
            merged_fields[existing_index] = field
    return merged_fields


def _apply_actions(page, actions: list[dict[str, Any]], logs: list[str]) -> list[str]:
    failed_actions: list[str] = []
    for action in actions:
        selector = action["selector"]
        locator = page.locator(selector).first
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
        except PlaywrightError:
            pass

        try:
            if action.get("mode") == "check":
                locator.check()
            elif action.get("mode") == "click":
                locator.click()
            elif action.get("mode") == "select":
                if not _select_option(locator, action["value"]):
                    logs.append(f"Could not select '{action['value']}' for field '{action['field']}'.")
                    failed_actions.append(str(action["field"]))
                    continue
            elif action.get("mode") == "choose":
                if not _choose_option(page, locator, action):
                    logs.append(
                        f"Could not choose '{action.get('option_label') or action['value']}' for field '{action['field']}'."
                    )
                    failed_actions.append(str(action["field"]))
                    continue
            elif action.get("mode") == "autocomplete":
                if not _autocomplete_option(page, locator, action):
                    logs.append(
                        f"Could not autocomplete '{action.get('option_label') or action['value']}' for field '{action['field']}'."
                    )
                    failed_actions.append(str(action["field"]))
                    continue
            elif action["field"] == "resume_path":
                resume_path = _resolve_resume_path(action["value"])
                if resume_path:
                    locator.set_input_files(resume_path)
                else:
                    logs.append("Resume file path was not available at execution time.")
                    failed_actions.append(str(action["field"]))
                    continue
            else:
                locator.fill(action["value"])
        except PlaywrightError as exc:
            logs.append(f"Failed to apply field '{action['field']}' using {selector}: {exc}")
            failed_actions.append(str(action["field"]))
            continue
        logs.append(f"Prepared field '{action['field']}' using {selector}.")
    return failed_actions


def _resolve_selector(page, platform: str, field: WorkerFieldState) -> str | None:
    candidates = _dedupe_selectors(
        [*field.selector_candidates, field.selector, *get_selector_fallbacks(platform, field.canonical_key)]
    )
    return _first_actionable_selector(page, [candidate for candidate in candidates if candidate])


def _resolve_option_selector(page, option) -> str | None:
    candidates = _dedupe_selectors([*option.selector_candidates, option.selector])
    return _first_actionable_selector(page, [candidate for candidate in candidates if candidate])


def _first_actionable_selector(page, selectors: list[str]) -> str | None:
    for selector in selectors:
        if _selector_exists(page, selector):
            return selector
    return None


def _dedupe_selectors(selectors: list[str | None]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        normalized = (selector or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _choose_option(page, locator, action: dict[str, Any]) -> bool:
    try:
        locator.click()
    except PlaywrightError:
        try:
            locator.press("ArrowDown")
        except PlaywrightError:
            return False

    try:
        page.wait_for_timeout(150)
    except PlaywrightError:
        pass

    option_locator = _locate_choice_option(page, action)
    if option_locator is None:
        return False

    try:
        option_locator.scroll_into_view_if_needed(timeout=2000)
    except PlaywrightError:
        pass
    option_locator.click()
    return True


def _autocomplete_option(page, locator, action: dict[str, Any]) -> bool:
    typed_value = str(action.get("value") or "").strip()
    if not typed_value:
        return False

    search_queries = [typed_value]
    if "," in typed_value:
        search_queries = [typed_value.split(",", 1)[0].strip(), typed_value]

    for query in _dedupe_selectors(search_queries):
        try:
            locator.click()
        except PlaywrightError:
            pass

        try:
            locator.fill(query)
        except PlaywrightError:
            try:
                locator.type(query, delay=20)
            except PlaywrightError:
                continue

        option_locator = _wait_for_choice_option(page, action)
        if option_locator is not None:
            try:
                option_locator.scroll_into_view_if_needed(timeout=2000)
            except PlaywrightError:
                pass

            try:
                option_locator.click()
            except PlaywrightError:
                continue

            if _autocomplete_selection_committed(page, locator):
                return True

        try:
            locator.press("ArrowDown")
            locator.press("Enter")
            page.wait_for_timeout(200)
        except PlaywrightError:
            continue

        if _autocomplete_selection_committed(page, locator):
            return True
    return False


def _wait_for_choice_option(page, action: dict[str, Any]):
    for wait_ms in (200, 400, 800, 1200):
        try:
            page.wait_for_timeout(wait_ms)
        except PlaywrightError:
            return None
        option_locator = _locate_choice_option(page, action)
        if option_locator is not None:
            return option_locator
    return None


def _autocomplete_selection_committed(page, locator) -> bool:
    try:
        page.wait_for_timeout(150)
    except PlaywrightError:
        return False

    try:
        return bool(
            locator.evaluate(
                """
                (element) => {
                  const input = element instanceof HTMLInputElement ? element : null
                  const ariaInvalid = (element.getAttribute('aria-invalid') || '').toLowerCase()
                  if (ariaInvalid === 'true') {
                    return false
                  }

                  let current = element
                  for (let depth = 0; depth < 5 && current; depth += 1) {
                    const selectedValue = current.querySelector?.('.select__single-value')
                    if (selectedValue && (selectedValue.textContent || '').trim()) {
                      return true
                    }
                    current = current.parentElement
                  }

                  return Boolean(input && (input.value || '').trim())
                }
                """
            )
        )
    except PlaywrightError:
        return False


def _locate_choice_option(page, action: dict[str, Any]):
    direct_selectors = _dedupe_selectors(
        [
            action.get("option_selector"),
            *(action.get("option_selector_candidates") or []),
        ]
    )
    for selector in direct_selectors:
        if _selector_exists(page, selector):
            return page.locator(selector).first

    for option_text in _dedupe_selectors(
        [action.get("option_label"), action.get("value")]
    ):
        quoted = json.dumps(option_text)
        text_selectors = [
            f"[role='option']:has-text({quoted})",
            f"[role='radio']:has-text({quoted})",
            f"[role='checkbox']:has-text({quoted})",
            f"li:has-text({quoted})",
            f"button:has-text({quoted})",
            f"label:has-text({quoted})",
            f"div[role='button']:has-text({quoted})",
        ]
        selector = _first_actionable_selector(page, text_selectors)
        if selector:
            return page.locator(selector).first
    return None


def _should_use_autocomplete(field: WorkerFieldState) -> bool:
    if field.field_type != "text":
        return False
    if field.canonical_key != "location":
        return False
    target = " ".join(
        part
        for part in [
            field.html_id or "",
            field.html_name or "",
            field.selector or "",
            field.label or "",
            field.question_text or "",
        ]
        if part
    ).lower()
    return "location" in target


def _react_select_option_candidates(field: WorkerFieldState) -> list[str]:
    html_id = (field.html_id or "").strip()
    if not html_id:
        return []
    return [
        f"#react-select-{html_id}-option-0",
        f"[id^='react-select-{html_id}-option-']",
    ]


def _selector_exists(page, selector: str) -> bool:
    try:
        locator = page.locator(selector).first
        return locator.count() > 0 and locator.is_visible()
    except PlaywrightError:
        return False


def _matching_option(field: WorkerFieldState, value: str):
    normalized_target = _normalize(value)
    for option in field.options:
        if _normalize(option.value) == normalized_target or _normalize(option.label) == normalized_target:
            return option
    return None


def _select_option(locator, value: str) -> bool:
    try:
        locator.select_option(label=value)
        return True
    except PlaywrightError:
        pass

    try:
        locator.select_option(value=value)
        return True
    except PlaywrightError:
        pass

    return False


def _resolve_resume_path(display_value: str) -> str | None:
    uploads = settings.data_dir / "uploads"
    candidate = uploads / display_value
    if candidate.exists():
        return str(candidate)
    if display_value and Path(display_value).exists():
        return display_value
    return None


def _save_screenshot(page, platform: str) -> str:
    screenshot_dir = settings.artifacts_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = screenshot_dir / f"{platform}-worker-{timestamp}-{uuid4().hex[:8]}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def _should_capture_screenshot(status: str) -> bool:
    return status in SCREENSHOT_CAPTURE_STATUSES


def _confirm_submission(page, initial_url: str) -> SubmissionConfirmationResult:
    _wait_for_post_submit(page)
    state = _read_post_submit_state(page)
    current_url = str(state["url"] or page.url or "")
    submitted_flag = str(state["submitted_flag"] or "").strip().lower()
    body_text = str(state["body_text"] or "").strip()
    combined_text = " ".join(
        segment for segment in [body_text, str(state["alert_text"] or "").strip()] if segment
    )
    normalized_current_url = _normalize_url(current_url)
    normalized_initial_url = _normalize_url(initial_url)

    if submitted_flag in {"1", "true", "yes"}:
        return SubmissionConfirmationResult(
            confirmed=True,
            outcome="confirmed",
            log="Detected submission confirmation via page submitted flag.",
        )

    if _matches_any(SUBMISSION_CONFIRMATION_TEXT_PATTERNS, combined_text):
        return SubmissionConfirmationResult(
            confirmed=True,
            outcome="confirmed",
            log="Detected submission confirmation from the resulting page text.",
        )

    if (
        normalized_current_url
        and normalized_current_url != normalized_initial_url
        and _matches_any(SUBMISSION_CONFIRMATION_URL_PATTERNS, normalized_current_url)
    ):
        return SubmissionConfirmationResult(
            confirmed=True,
            outcome="confirmed",
            log=f"Detected submission confirmation via redirect to {current_url}.",
        )

    if _matches_any(VERIFICATION_REQUIRED_TEXT_PATTERNS, combined_text):
        return SubmissionConfirmationResult(
            confirmed=False,
            outcome="verification",
            log="Submit was clicked, and the ATS is asking for an email or verification code before final confirmation.",
        )

    invalid_form_count = int(state["invalid_form_count"] or 0)
    invalid_field_count = int(state["invalid_field_count"] or 0)
    if invalid_form_count > 0 or invalid_field_count > 0:
        invalid_field_names = [
            str(item.get("label") or item.get("selector") or "").strip()
            for item in (state.get("invalid_fields") or [])
            if str(item.get("label") or item.get("selector") or "").strip()
        ]
        invalid_field_summary = ""
        if invalid_field_names:
            invalid_field_summary = f" Invalid fields: {', '.join(invalid_field_names[:3])}."
        return SubmissionConfirmationResult(
            confirmed=False,
            outcome="invalid",
            log=(
                "Submit was clicked, but the form still appears invalid; ATS confirmation was not detected."
                f"{invalid_field_summary}"
            ),
        )

    if _matches_any(VALIDATION_ERROR_TEXT_PATTERNS, combined_text):
        return SubmissionConfirmationResult(
            confirmed=False,
            outcome="invalid",
            log="Submit was clicked, but the resulting page still shows validation or error text.",
        )

    visible_form_count = int(state.get("visible_form_count") or 0)
    visible_submit_count = int(state.get("visible_submit_count") or 0)

    if (
        normalized_current_url == normalized_initial_url
        and visible_form_count > 0
        and visible_submit_count > 0
    ):
        return SubmissionConfirmationResult(
            confirmed=False,
            outcome="verification",
            log=(
                "Submit was clicked, but the application form is still visible without validation errors. "
                "A verification or follow-up confirmation step may be required."
            ),
        )

    return SubmissionConfirmationResult(
        confirmed=False,
        outcome="unconfirmed",
        log="Submit was clicked, but ATS confirmation was not detected on the resulting page.",
    )


def _wait_for_post_submit(page) -> None:
    for timeout in (600, 1200, 2400):
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
            return
        except PlaywrightTimeoutError:
            try:
                page.wait_for_timeout(200)
            except PlaywrightError:
                return
        except PlaywrightError:
            return


def _read_post_submit_state(page) -> dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const isVisible = (element) => {
            if (!(element instanceof HTMLElement)) return false
            const style = window.getComputedStyle(element)
            const rect = element.getBoundingClientRect()
            return (
              style.display !== 'none' &&
              style.visibility !== 'hidden' &&
              rect.width > 0 &&
              rect.height > 0
            )
          }

          const forms = Array.from(document.forms)
          const visibleFormCount = forms.filter((form) => isVisible(form)).length
          const invalidFormCount = forms.filter((form) => {
            try {
              return !form.checkValidity()
            } catch (_error) {
              return false
            }
          }).length

          const invalidFieldCount = Array.from(
            document.querySelectorAll(
              "input:invalid, textarea:invalid, select:invalid, [aria-invalid='true']"
            )
          ).filter(isVisible).length

          const alertText = Array.from(
            document.querySelectorAll(
              "[role='alert'], .error, .errors, .field-error, .flash-error, .validation-error, .invalid-feedback"
            )
          )
            .map((element) => (element.textContent || '').trim())
            .filter(Boolean)
            .join(' ')

          const visibleSubmitCount = Array.from(
            document.querySelectorAll("button[type='submit'], input[type='submit']")
          ).filter(isVisible).length

          const invalidFields = Array.from(
            document.querySelectorAll(
              "input:invalid, textarea:invalid, select:invalid, [aria-invalid='true']"
            )
          )
            .filter(isVisible)
            .map((element) => {
              const candidate = element
              const labelText =
                (candidate.labels && candidate.labels[0] ? candidate.labels[0].innerText : '') ||
                (candidate.getAttribute('aria-label') || '') ||
                (candidate.getAttribute('name') || '') ||
                (candidate.getAttribute('id') || '')
              return {
                label: labelText.replace(/\\s+/g, ' ').trim(),
                selector: candidate.getAttribute('id') ? `#${candidate.getAttribute('id')}` : '',
                validation_message:
                  'validationMessage' in candidate ? String(candidate.validationMessage || '').trim() : '',
              }
            })

          return {
            url: window.location.href,
            submitted_flag: document.body?.dataset?.submitted || '',
            body_text: (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 5000),
            alert_text: alertText.slice(0, 1000),
            visible_form_count: visibleFormCount,
            visible_submit_count: visibleSubmitCount,
            invalid_form_count: invalidFormCount,
            invalid_field_count: invalidFieldCount,
            invalid_fields: invalidFields.slice(0, 5),
          }
        }
        """
    )


def _matches_any(patterns: list[re.Pattern[str]], value: str) -> bool:
    if not value.strip():
        return False
    return any(pattern.search(value) for pattern in patterns)


def _normalize_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return ""
    return normalized.split("#", 1)[0]


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())
