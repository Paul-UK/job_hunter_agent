from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
            screenshot_path = _save_screenshot(page, platform)

            blocking_review = any(field.required and field.requires_review for field in review_items)
            if blocking_review:
                status = "awaiting_answers"
                logs.append("Required questions still need review before autofill can proceed.")
            elif request.dry_run:
                status = "preview_ready"
                logs.append("Preview generated; no fields were submitted.")
            elif not request.confirm_submit:
                _apply_actions(page, actions, logs)
                status = "ready_for_submit"
                logs.append("Filled high-confidence fields and paused before submit.")
            else:
                _apply_actions(page, actions, logs)
                submit_selector = _first_actionable_selector(page, get_submit_hints(platform))
                if submit_selector:
                    page.locator(submit_selector).first.click()
                    status = "submitted"
                    logs.append(f"Clicked submit using {submit_selector}.")
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
        if not value or field.requires_review:
            continue

        if field.field_type in {"radio", "checkbox"}:
            option = _matching_option(field, value)
            if option and option.selector and _selector_exists(page, option.selector):
                actions.append(
                    WorkerActionPayload(
                        field=field.canonical_key or field.label or field.field_id,
                        selector=option.selector,
                        value=option.value or option.label,
                        field_id=field.field_id,
                        mode="check",
                    ).model_dump(mode="json")
                )
                continue

        selector = _resolve_selector(page, platform, field)
        if not selector:
            logs.append(
                f"No actionable selector found for '{field.label or field.field_id}'."
            )
            continue

        mode = "select" if field.field_type == "select" else "fill"
        actions.append(
            WorkerActionPayload(
                field=field.canonical_key or field.label or field.field_id,
                selector=selector,
                value=value if field.canonical_key != "resume_path" else Path(value).name,
                field_id=field.field_id,
                mode=mode,
            ).model_dump(mode="json")
        )
    return actions


def _apply_actions(page, actions: list[dict[str, Any]], logs: list[str]) -> None:
    for action in actions:
        selector = action["selector"]
        locator = page.locator(selector).first
        try:
            locator.scroll_into_view_if_needed(timeout=2000)
        except PlaywrightError:
            pass

        if action.get("mode") == "check":
            locator.check()
        elif action.get("mode") == "select":
            if not _select_option(locator, action["value"]):
                logs.append(f"Could not select '{action['value']}' for field '{action['field']}'.")
                continue
        elif action["field"] == "resume_path":
            resume_path = _resolve_resume_path(action["value"])
            if resume_path:
                locator.set_input_files(resume_path)
            else:
                logs.append("Resume file path was not available at execution time.")
                continue
        else:
            locator.fill(action["value"])
        logs.append(f"Prepared field '{action['field']}' using {selector}.")


def _resolve_selector(page, platform: str, field: WorkerFieldState) -> str | None:
    candidates = [field.selector, *get_selector_fallbacks(platform, field.canonical_key)]
    return _first_actionable_selector(page, [candidate for candidate in candidates if candidate])


def _first_actionable_selector(page, selectors: list[str]) -> str | None:
    for selector in selectors:
        if _selector_exists(page, selector):
            return selector
    return None


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


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())
