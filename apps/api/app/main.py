from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.config import settings
from apps.api.app.db import migrate_database
from apps.api.app.routers import applications, jobs, meta, profiles, searches, tasks


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate_database()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta.router)
app.include_router(profiles.router)
app.include_router(jobs.router)
app.include_router(applications.router)
app.include_router(searches.router)
app.include_router(tasks.router)
