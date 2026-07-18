import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from backend.app.database import engine


logger = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def ensure_migration_table() -> None:
    statement = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version VARCHAR(255) PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL
    )
    """
    with engine.begin() as connection:
        connection.execute(text(statement))


def applied_versions() -> set[str]:
    ensure_migration_table()
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT version FROM schema_migrations"))
        return {row[0] for row in rows}


def run_migration(version: str, sql_text: str) -> None:
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        cursor.execute(sql_text)
        cursor.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
            (version, datetime.now(UTC)),
        )
        raw_connection.commit()
        logger.info("Applied migration %s", version)
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def upgrade() -> list[str]:
    completed = applied_versions()
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in completed:
            continue
        run_migration(path.name, path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", force=True)
    parser = argparse.ArgumentParser(description="Run Qubitx database migrations")
    parser.add_argument("command", choices=["upgrade", "status"])
    args = parser.parse_args()

    if args.command == "upgrade":
        applied = upgrade()
        if applied:
            print("\n".join(applied))
        else:
            print("No pending migrations")
        return

    print("\n".join(sorted(applied_versions())))


if __name__ == "__main__":
    main()
