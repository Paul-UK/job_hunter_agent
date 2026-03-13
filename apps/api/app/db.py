from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from apps.api.app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()
SCHEMA_MIGRATION_TABLE = "schema_migrations"
MIGRATION_COLUMNS = {
    "candidate_profiles": {
        "search_preferences": "JSON NOT NULL DEFAULT '{}'",
        "search_preferences_customized": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "job_leads": {
        "discovery_method": "VARCHAR(32) NOT NULL DEFAULT 'direct'",
        "crm_stage": "VARCHAR(32) NOT NULL DEFAULT 'new'",
        "crm_notes": "TEXT",
        "follow_up_at": "DATETIME",
        "last_contacted_at": "DATETIME",
        "first_seen_at": "DATETIME",
        "last_seen_at": "DATETIME",
        "last_checked_at": "DATETIME",
        "closed_at": "DATETIME",
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
    },
    "worker_runs": {
        "fields": "JSON NOT NULL DEFAULT '[]'",
        "review_items": "JSON NOT NULL DEFAULT '[]'",
        "preview_summary": "JSON NOT NULL DEFAULT '{}'",
        "profile_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "job_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "draft_snapshot": "JSON NOT NULL DEFAULT '{}'",
        "updated_at": "DATETIME",
    },
}


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@dataclass(frozen=True, slots=True)
class MigrationRevision:
    version: int
    name: str
    apply: Callable[[Connection], None]


def migrate_database() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        applied_versions = _load_applied_versions(connection)
        for revision in MIGRATION_REVISIONS:
            if revision.version in applied_versions:
                continue
            revision.apply(connection)
            connection.exec_driver_sql(
                f"INSERT INTO {SCHEMA_MIGRATION_TABLE} (version, name) VALUES (?, ?)",
                (revision.version, revision.name),
            )


def ensure_runtime_schema() -> None:
    migrate_database()


def _load_applied_versions(connection: Connection) -> set[int]:
    inspector = inspect(connection)
    if SCHEMA_MIGRATION_TABLE not in inspector.get_table_names():
        return set()
    return {
        int(row[0])
        for row in connection.exec_driver_sql(
            f"SELECT version FROM {SCHEMA_MIGRATION_TABLE} ORDER BY version"
        ).fetchall()
    }


def _apply_platform_upgrade_foundations(connection: Connection) -> None:
    for table_name, columns in MIGRATION_COLUMNS.items():
        for column_name, column_ddl in columns.items():
            _add_column_if_missing(connection, table_name, column_name, column_ddl)

    _backfill_platform_upgrade_foundations(connection)

    for ddl in [
        "CREATE INDEX IF NOT EXISTS ix_saved_searches_profile_id ON saved_searches (profile_id)",
        "CREATE INDEX IF NOT EXISTS ix_saved_searches_next_run_at ON saved_searches (enabled, next_run_at)",
        "CREATE INDEX IF NOT EXISTS ix_discovery_runs_saved_search_id ON discovery_runs (saved_search_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_saved_search_matches_saved_search_id ON saved_search_matches (saved_search_id, current_score)",
        "CREATE INDEX IF NOT EXISTS ix_background_tasks_status_scheduled_at ON background_tasks (status, scheduled_at)",
        "CREATE INDEX IF NOT EXISTS ix_background_tasks_saved_search_id ON background_tasks (saved_search_id)",
        "CREATE INDEX IF NOT EXISTS ix_background_tasks_application_draft_id ON background_tasks (application_draft_id)",
    ]:
        connection.exec_driver_sql(ddl)


def _add_column_if_missing(
    connection: Connection,
    table_name: str,
    column_name: str,
    column_ddl: str,
) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    if table_name not in existing_tables:
        return
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return
    connection.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}")


def _backfill_platform_upgrade_foundations(connection: Connection) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    if "candidate_profiles" in existing_tables:
        connection.exec_driver_sql(
            """
            UPDATE candidate_profiles
            SET
              search_preferences = COALESCE(search_preferences, '{}'),
              search_preferences_customized = COALESCE(search_preferences_customized, 0)
            """
        )

    if "job_leads" in existing_tables:
        connection.exec_driver_sql(
            """
            UPDATE job_leads
            SET
              discovery_method = COALESCE(discovery_method, 'direct'),
              crm_stage = COALESCE(crm_stage, 'new'),
              is_active = COALESCE(is_active, 1),
              first_seen_at = COALESCE(first_seen_at, created_at, CURRENT_TIMESTAMP),
              last_seen_at = COALESCE(last_seen_at, updated_at, created_at, CURRENT_TIMESTAMP),
              last_checked_at = COALESCE(last_checked_at, updated_at, created_at, CURRENT_TIMESTAMP)
            """
        )

    if "worker_runs" in existing_tables:
        connection.exec_driver_sql(
            """
            UPDATE worker_runs
            SET
              fields = COALESCE(fields, '[]'),
              review_items = COALESCE(review_items, '[]'),
              preview_summary = COALESCE(preview_summary, '{}'),
              profile_snapshot = COALESCE(profile_snapshot, '{}'),
              job_snapshot = COALESCE(job_snapshot, '{}'),
              draft_snapshot = COALESCE(draft_snapshot, '{}'),
              updated_at = COALESCE(updated_at, created_at)
            """
        )


def _apply_submission_status_statefulness(connection: Connection) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    required_tables = {"worker_runs", "application_drafts", "job_leads"}
    if not required_tables.issubset(existing_tables):
        return

    connection.exec_driver_sql(
        """
        UPDATE worker_runs
        SET status = 'submit_failed'
        WHERE status = 'submit_clicked'
          AND logs LIKE '%form still appears invalid%'
        """
    )

    connection.exec_driver_sql(
        """
        UPDATE application_drafts
        SET status = 'submit_failed'
        WHERE status = 'submit_clicked'
          AND id IN (
            SELECT DISTINCT application_draft_id
            FROM worker_runs
            WHERE status = 'submit_failed'
              AND application_draft_id IS NOT NULL
          )
        """
    )

    connection.exec_driver_sql(
        """
        UPDATE job_leads
        SET status = 'submit_failed'
        WHERE status = 'submit_clicked'
          AND id IN (
            SELECT DISTINCT job_lead_id
            FROM application_drafts
            WHERE status = 'submit_failed'
          )
        """
    )


MIGRATION_REVISIONS = (
    MigrationRevision(
        version=1,
        name="platform_upgrade_foundations",
        apply=_apply_platform_upgrade_foundations,
    ),
    MigrationRevision(
        version=2,
        name="submission_status_statefulness",
        apply=_apply_submission_status_statefulness,
    ),
)
