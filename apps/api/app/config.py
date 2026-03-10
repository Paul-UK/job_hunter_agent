from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Job Hunting Agent"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    web_origin: str = "http://localhost:5173"
    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'app.db'}"
    data_dir: Path = Field(default=ROOT_DIR / "data")
    artifacts_dir: Path = Field(default=ROOT_DIR / "artifacts")
    github_token: str | None = None
    default_dry_run: bool = True
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(
        env_prefix="JOB_AGENT_",
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
