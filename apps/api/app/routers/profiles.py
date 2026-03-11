from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from apps.api.app.config import settings
from apps.api.app.db import get_session
from apps.api.app.schemas import (
    CandidateProfileResponse,
    DeleteResponse,
    ProfileSourcePayload,
    ProfileUpdateRequest,
)
from apps.api.app.services.profile_sources.linkedin_profile import parse_linkedin_source
from apps.api.app.services.resume_parser import extract_text_from_upload, parse_resume_text
from apps.api.app.services.storage import (
    delete_profile_source,
    get_latest_profile,
    list_profile_sources,
    save_profile_source,
    update_profile_manually,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=CandidateProfileResponse | None)
def read_profile(session: Session = Depends(get_session)) -> CandidateProfileResponse | None:
    return get_latest_profile(session)


@router.get("/sources", response_model=list[ProfileSourcePayload])
def read_profile_sources(session: Session = Depends(get_session)) -> list[ProfileSourcePayload]:
    return list_profile_sources(session)


@router.delete("/sources/{source_id}", response_model=DeleteResponse)
def remove_profile_source(source_id: int, session: Session = Depends(get_session)) -> DeleteResponse:
    deleted_counts = delete_profile_source(session, source_id)
    if deleted_counts is None:
        raise HTTPException(status_code=404, detail="Profile source not found.")
    return DeleteResponse(
        entity="profile_source",
        deleted_id=source_id,
        deleted_counts=deleted_counts,
    )


@router.post("/cv", response_model=CandidateProfileResponse)
async def upload_cv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> CandidateProfileResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded CV file is empty.")
    text = extract_text_from_upload(file.filename or "resume.txt", content)
    payload = parse_resume_text(text)
    profile = save_profile_source(
        session,
        source_type="cv",
        source_label=file.filename or "CV upload",
        raw_text=text,
        payload=payload,
        confidence={"text_extracted": 1.0, "structured_fields": 0.8},
    )
    saved_path = _persist_resume_file(file.filename or "resume.txt", content)
    merged_profile = dict(profile.merged_profile)
    merged_links = dict(merged_profile.get("links", {}))
    merged_links["resume_path"] = saved_path
    merged_profile["links"] = merged_links
    profile.merged_profile = merged_profile
    session.commit()
    session.refresh(profile)
    return profile


@router.post("/linkedin", response_model=CandidateProfileResponse)
async def upload_linkedin_profile(
    text: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    session: Session = Depends(get_session),
) -> CandidateProfileResponse:
    raw_text = text or ""
    source_label = "LinkedIn paste"
    is_html = False

    if file is not None:
        content = await file.read()
        raw_text = content.decode("utf-8", errors="ignore")
        source_label = file.filename or source_label
        is_html = (file.filename or "").lower().endswith((".html", ".htm"))

    if not raw_text.strip():
        raise HTTPException(
            status_code=400, detail="Provide LinkedIn profile text or upload a file."
        )

    payload, confidence = parse_linkedin_source(raw_text, is_html=is_html)
    profile = save_profile_source(
        session,
        source_type="linkedin",
        source_label=source_label,
        raw_text=raw_text,
        payload=payload,
        confidence=confidence,
    )
    return profile


@router.put("", response_model=CandidateProfileResponse)
def update_profile(
    payload: ProfileUpdateRequest,
    session: Session = Depends(get_session),
) -> CandidateProfileResponse:
    return update_profile_manually(session, payload)


def _persist_resume_file(filename: str, content: bytes) -> str:
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".txt"
    target = upload_dir / f"latest_resume{suffix}"
    target.write_bytes(content)
    return str(target)
