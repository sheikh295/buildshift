from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from buildshift_orchestrator.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Renamed migration files → previous filenames (already applied DBs stay compatible)
_LEGACY_MIGRATION_ALIASES = {
    "002_prd_planning.sql": "002_week2.sql",
    "003_runtime_settings.sql": "003_week3.sql",
}


def apply_migrations() -> None:
    settings = get_settings()
    migrations_dir = settings.migrations_dir
    if not migrations_dir.exists():
        # Local editable install: apps/orchestrator/migrations
        migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
    if not migrations_dir.exists():
        raise FileNotFoundError(f"migrations not found at {settings.migrations_dir}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        applied = {
            row[0]
            for row in conn.execute(text("SELECT filename FROM schema_migrations")).fetchall()
        }
        # Record current names when only the legacy filename was applied
        for new_name, old_name in _LEGACY_MIGRATION_ALIASES.items():
            if old_name in applied and new_name not in applied:
                conn.execute(
                    text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                    {"f": new_name},
                )
                applied.add(new_name)
        for path in sorted(migrations_dir.glob("*.sql")):
            if path.name in applied:
                continue
            legacy = _LEGACY_MIGRATION_ALIASES.get(path.name)
            if legacy and legacy in applied:
                continue
            conn.execute(text(path.read_text()))
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                {"f": path.name},
            )
