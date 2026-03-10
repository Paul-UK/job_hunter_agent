# Job Hunting Agent

Local-first dashboard and browser worker for accelerating job search workflows without removing human approval from final submission.

## What it does

- Parses a CV from PDF, DOCX, or text and normalizes it into a structured candidate profile.
- Optionally enriches that profile with LinkedIn text or exported HTML.
- Discovers job leads from Greenhouse and Lever, plus manually captured LinkedIn leads.
- Scores roles against the profile, adds company and GitHub research, and drafts tailored application material.
- Runs a guarded Playwright autofill pass that pauses before submit and logs the planned actions.

## Stack

- Backend: `FastAPI`, `SQLAlchemy`, `SQLite`
- Frontend: `React`, `TypeScript`, `Vite`
- Worker: `Playwright` on Python

## Quick start

1. Copy `.env.example` to `.env` if you want custom settings.
2. Install browser binaries:

```bash
uv run playwright install chromium
```

3. Start the API and web app together:

```bash
uv run python scripts/dev.py
```

4. Open `http://localhost:5173`.

## API highlights

- `POST /api/profile/cv`
- `POST /api/profile/linkedin`
- `PUT /api/profile`
- `POST /api/jobs/discover/greenhouse`
- `POST /api/jobs/discover/lever`
- `POST /api/jobs/discover/linkedin`
- `POST /api/jobs/{job_id}/research`
- `POST /api/jobs/{job_id}/draft`
- `POST /api/applications/{application_id}/run`

## Safety defaults

- LinkedIn is discovery-only for job leads.
- Worker runs default to dry-run mode.
- Final submit requires explicit confirmation in the worker request.
