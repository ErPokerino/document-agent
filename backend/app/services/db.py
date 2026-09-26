"""One way to open the application database, shared by every store.

Four stores write the same file: workspace runs, Lab evaluations, the register
and the supplier rules. Under SQLite's default rollback journal a writer locks
every reader out, so a Lab run recording a document result could fail a list
request in the UI with `database is locked`. Write-ahead logging lets readers
carry on during a write; the busy timeout covers the remaining writer-writer
case.

One connection per operation: sqlite3 connections are not safe to share
between threads, and these operations are short.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Longer than any write these stores make, which are single rows or one run.
BUSY_TIMEOUT_SECONDS = 10


def prepare(path: Path) -> None:
    """Switch the file to write-ahead logging. The mode persists in the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    finally:
        connection.close()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def add_missing_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add each column the table lacks, for a database written by an older app.

    `columns` maps a name to its declaration. A column is only ever added,
    never altered, so an older row reads back with the declared default.
    """
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
