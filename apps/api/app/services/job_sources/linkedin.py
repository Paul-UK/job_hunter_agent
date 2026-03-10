from __future__ import annotations

from urllib.parse import urlparse

from apps.api.app.schemas import LinkedinLeadRequest


def create_linkedin_lead(payload: LinkedinLeadRequest) -> dict:
    parsed_url = urlparse(str(payload.url)) if payload.url else None
    external_id = (
        parsed_url.path.strip("/").replace("/", "-")
        if parsed_url
        else f"{payload.company}-{payload.title}"
    )
    description = payload.description or payload.notes or "LinkedIn lead captured for later review."
    return {
        "source": "linkedin",
        "external_id": external_id,
        "company": payload.company,
        "title": payload.title,
        "location": payload.location,
        "employment_type": None,
        "url": str(payload.url) if payload.url else "",
        "description": description,
        "requirements": [],
        "metadata_json": {
            "capture_mode": "manual",
            "notes": payload.notes,
        },
    }
