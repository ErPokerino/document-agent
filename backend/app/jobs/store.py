"""Long work recorded in the database, so whoever runs it can be somewhere else.

A Lab run, an experiment, a training run and a fine-tuning export each become
one row here when they are asked for. The row says what to do (`kind` and
`payload`), how far it got, and whether someone asked it to stop. The API
writes it and returns at once; the work is then done by the API process itself
or by a separate worker (`app.worker`), and either one reports progress and
the outcome back into the same row. That is what lets the API scale to zero
between requests without killing a run, and the UI poll one place whatever ran
the work.
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.services import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT    NOT NULL,
    name             TEXT    NOT NULL,
    subject_id       INTEGER,
    payload_json     TEXT    NOT NULL,
    status           TEXT    NOT NULL,
    created_at       TEXT    NOT NULL,
    started_at       TEXT,
    finished_at      TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    total            INTEGER NOT NULL DEFAULT 0,
    done             INTEGER NOT NULL DEFAULT 0,
    phase            TEXT,
    artifact_id      TEXT,
    output           TEXT,
    examples         INTEGER NOT NULL DEFAULT 0,
    skipped_json     TEXT,
    error            TEXT
);
CREATE INDEX IF NOT EXISTS jobs_kind_subject ON jobs(kind, subject_id);
"""

TERMINAL_STATUSES = ("completed", "failed", "cancelled")
# Fields the work itself may report while it runs.
PROGRESS_FIELDS = ("total", "done", "phase", "artifact_id", "output", "examples", "skipped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: int
    kind: str
    name: str
    subject_id: int | None
    payload: dict[str, Any]
    # "running" from the moment it is asked for: a job waiting for a worker
    # to start is already under way as far as anyone watching is concerned.
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    cancel_requested: bool = False
    total: int = 0
    done: int = 0
    phase: str | None = None
    artifact_id: str | None = None
    output: str | None = None
    examples: int = 0
    skipped: list[str] = field(default_factory=list)
    error: str | None = None


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        db.prepare(self.path)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        with db.connect(self.path) as connection:
            yield connection

    @staticmethod
    def _job(row: Any) -> Job:
        return Job(
            id=int(row["id"]),
            kind=row["kind"],
            name=row["name"],
            subject_id=row["subject_id"],
            payload=json.loads(row["payload_json"]),
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            cancel_requested=bool(row["cancel_requested"]),
            total=int(row["total"] or 0),
            done=int(row["done"] or 0),
            phase=row["phase"],
            artifact_id=row["artifact_id"],
            output=row["output"],
            examples=int(row["examples"] or 0),
            skipped=json.loads(row["skipped_json"]) if row["skipped_json"] else [],
            error=row["error"],
        )

    def create(self, kind: str, name: str, payload: dict[str, Any], *, subject_id: int | None = None, total: int = 0) -> Job:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO jobs (kind, name, subject_id, payload_json, status, created_at, total) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?)",
                (kind, name, subject_id, json.dumps(payload, ensure_ascii=False), _now(), total),
            )
            job_id = int(cursor.lastrowid)
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: int) -> Job | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def for_subject(self, kind: str, subject_id: int) -> Job | None:
        """The latest job that worked on this evaluation or experiment."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE kind = ? AND subject_id = ? ORDER BY id DESC LIMIT 1",
                (kind, subject_id),
            ).fetchone()
        return self._job(row) if row else None

    def latest(self, kinds: tuple[str, ...], limit: int = 20) -> list[Job]:
        placeholders = ",".join("?" for _ in kinds)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE kind IN ({placeholders}) ORDER BY id DESC LIMIT ?",
                (*kinds, limit),
            ).fetchall()
        return [self._job(row) for row in rows]

    def active(self, kinds: tuple[str, ...]) -> Job | None:
        placeholders = ",".join("?" for _ in kinds)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM jobs WHERE kind IN ({placeholders}) AND status = 'running' ORDER BY id LIMIT 1",
                kinds,
            ).fetchone()
        return self._job(row) if row else None

    def started(self, job_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE jobs SET started_at = ? WHERE id = ?", (_now(), job_id))

    def progress(self, job_id: int, **changes: Any) -> None:
        """Record how far a running job got. A finished one is left alone."""
        unknown = set(changes) - set(PROGRESS_FIELDS)
        if unknown:
            raise ValueError(f"Not progress fields: {', '.join(sorted(unknown))}")
        if "skipped" in changes:
            changes["skipped_json"] = json.dumps(changes.pop("skipped"), ensure_ascii=False)
        if not changes:
            return
        assignments = ", ".join(f"{name} = ?" for name in changes)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ? AND status = 'running'",
                (*changes.values(), job_id),
            )

    def finish(self, job_id: int, status: str, error: str | None = None) -> None:
        """Close a running job. A cancelled one stays cancelled when its work ends later."""
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"{status!r} is not a terminal job status")
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, error = ?, phase = NULL "
                "WHERE id = ? AND status = 'running'",
                (status, _now(), error, job_id),
            )

    def request_cancel(self, job_id: int) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))

    def cancel_requested(self, job_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def mark_interrupted(self) -> int:
        """Close jobs left running by an API process that stopped while doing them itself."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status = 'failed', finished_at = ?, error = 'Interrupted by a backend restart' "
                "WHERE status = 'running'",
                (_now(),),
            )
            return cursor.rowcount
