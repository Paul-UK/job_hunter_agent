from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from apps.api.app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()
SQLITE_RUNTIME_COLUMNS = {
    "candidate_profiles": {
        "search_preferences": "JSON NOT NULL DEFAULT '{}'",
        "search_preferences_customized": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "job_leads": {
        "discovery_method": "VARCHAR(32) NOT NULL DEFAULT 'direct'",
    },
    "worker_runs": {
        "fields": "JSON NOT NULL DEFAULT '[]'",
        "review_items": "JSON NOT NULL DEFAULT '[]'",
        "preview_summary": "JSON NOT NULL DEFAULT '{}'",
        "profile_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "job_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "draft_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "updated_at": "DATETIME",
    }
}


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def ensure_runtime_schema() -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        for table_name, columns in SQLITE_RUNTIME_COLUMNS.items():
            existing_columns = {
                row[1]
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
            }
            for column_name, column_ddl in columns.items():
                if column_name in existing_columns:
                    continue
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}"
                )
