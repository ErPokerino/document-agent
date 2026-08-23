"""The supplier register: internal identifiers a document never carries.

A document says "UL VS LTD". Whatever handles it downstream needs the internal
id for that supplier, which appears nowhere on the page. This is the table that
holds the correspondence, and the one thing that must be true of it is that a
supplier appears exactly once: two rows for the same company mean a lookup has
two right answers.

The identifier is a running number and is never reused, so a deleted row cannot
come back meaning a different supplier in a run recorded earlier.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from app.services.similarity import normalize_company_name


SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    id_subject      TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL,
    normalized_name TEXT    NOT NULL UNIQUE,
    created_at      TEXT    NOT NULL,
    source          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS subject_counter (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    next INTEGER NOT NULL
);
"""


class UnknownSubject(LookupError):
    """No supplier is registered under that identifier."""


class DuplicateSubject(ValueError):
    """That supplier is already in the register under another spelling."""


@dataclass(frozen=True)
class Subject:
    id_subject: str
    name: str
    normalized_name: str
    created_at: str
    source: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SubjectStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT INTO subject_counter (id, next) VALUES (1, 1) ON CONFLICT(id) DO NOTHING"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def list(self, query: str = "") -> "list[Subject]":
        """Every supplier, by name. `query` matches either spelling."""
        needle = f"%{query.strip().lower()}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM subjects
                WHERE ? = '%%' OR lower(name) LIKE ? OR normalized_name LIKE ?
                ORDER BY name COLLATE NOCASE
                """,
                (needle, needle, needle),
            ).fetchall()
        return [_subject(row) for row in rows]

    def read(self, id_subject: str) -> Subject:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM subjects WHERE id_subject = ?", (id_subject,)
            ).fetchone()
        if row is None:
            raise UnknownSubject(f"No supplier with id {id_subject!r}")
        return _subject(row)

    def add(self, name: str, source: str = "manual") -> Subject:
        normalized = normalize_company_name(name)
        if not normalized:
            raise ValueError("A supplier needs a name")
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM subjects WHERE normalized_name = ?", (normalized,)
            ).fetchone()
            if existing is not None:
                raise DuplicateSubject(
                    f"{existing['name']} is already registered as {existing['id_subject']}"
                )
            id_subject = _claim_identifier(connection)
            connection.execute(
                """
                INSERT INTO subjects (id_subject, name, normalized_name, created_at, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (id_subject, name.strip(), normalized, _now(), source),
            )
        return self.read(id_subject)

    def update(self, id_subject: str, *, name: str) -> Subject:
        normalized = normalize_company_name(name)
        if not normalized:
            raise ValueError("A supplier needs a name")
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM subjects WHERE id_subject = ?", (id_subject,)
            ).fetchone() is None:
                raise UnknownSubject(f"No supplier with id {id_subject!r}")
            clash = connection.execute(
                "SELECT * FROM subjects WHERE normalized_name = ? AND id_subject <> ?",
                (normalized, id_subject),
            ).fetchone()
            if clash is not None:
                raise DuplicateSubject(
                    f"{clash['name']} is already registered as {clash['id_subject']}"
                )
            connection.execute(
                "UPDATE subjects SET name = ?, normalized_name = ? WHERE id_subject = ?",
                (name.strip(), normalized, id_subject),
            )
        return self.read(id_subject)

    def delete(self, id_subject: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM subjects WHERE id_subject = ?", (id_subject,)
            )
            if cursor.rowcount == 0:
                raise UnknownSubject(f"No supplier with id {id_subject!r}")

    def seed(self, names: Iterable[str], source: str = "datasets") -> "list[Subject]":
        """Register the names not already there, and return only those.

        A name that normalizes onto an existing row is skipped rather than
        merged: whoever corrected that row knew better than this list does.
        """
        added: list[Subject] = []
        for name in names:
            try:
                added.append(self.add(name, source=source))
            except (DuplicateSubject, ValueError):
                continue
        return added


def _claim_identifier(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT next FROM subject_counter WHERE id = 1").fetchone()
    number = int(row["next"])
    connection.execute("UPDATE subject_counter SET next = ? WHERE id = 1", (number + 1,))
    return f"S{number:04d}"


def _subject(row: sqlite3.Row) -> Subject:
    return Subject(
        id_subject=row["id_subject"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        created_at=row["created_at"],
        source=row["source"],
    )
