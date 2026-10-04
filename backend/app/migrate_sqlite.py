"""Copy a local SQLite database into the configured PostgreSQL one, once.

Moving an installation to the cloud keeps its history: every run, Lab result,
experiment, supplier and rule. The target's tables are made by the stores
themselves (importing the API opens all of them), then each source table is
copied column by column into its namesake, and each key sequence is moved
past the copied ids so new rows do not collide with old ones.

Refuses, and copies nothing, when any target table already holds rows: a
second run would duplicate history rather than update it.

    python -m app.worker migrate-sqlite /data/migration/docuflow.db
"""

import sqlite3
from pathlib import Path

from app import config


def copy_sqlite(source: Path) -> dict[str, int]:
    if not config.database_url():
        raise SystemExit("DOCUFLOW_DATABASE_URL is not set: there is no PostgreSQL database to copy into.")
    if not source.is_file():
        raise SystemExit(f"No SQLite database at {source}")

    from app.api import deps
    from app.services import db

    origin = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in origin.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
            )
        ]
        copied: dict[str, int] = {}
        with db.connect(deps.DATABASE_PATH) as target:
            columns_of: dict[str, set[str]] = {}
            for table in tables:
                columns_of[table] = {
                    row[0]
                    for row in target.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = ?",
                        (table,),
                    )
                }
                if columns_of[table]:
                    held = target.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    if held:
                        raise SystemExit(f"{table} already holds {held} rows in the target database. Nothing was copied.")
            # Parents before children: tables are copied in the order they were created.
            for table in tables:
                if not columns_of[table]:
                    print(f"{table}: no such table in the target database, skipped")
                    continue
                source_columns = [row[1] for row in origin.execute(f"PRAGMA table_info({table})")]
                columns = [name for name in source_columns if name in columns_of[table]]
                rows = origin.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
                if rows:
                    target.executemany(
                        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                        rows,
                    )
                if "id" in columns:
                    target.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
                    )
                copied[table] = len(rows)
                print(f"{table}: {len(rows)} rows")
        return copied
    finally:
        origin.close()
