"""Persisted evaluation runs: what was scored, against which prompts, and how well.

Every run snapshots the prompts and the model that produced it. Comparing two
evaluations is only meaningful if each one remembers the configuration it ran
with, rather than reading today's settings.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.domain.models import PromptConfiguration
from app.evaluation.scoring import EvaluationMetrics, FieldOutcome, aggregate


SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL,
    finished_at         TEXT,
    dataset             TEXT    NOT NULL,
    model               TEXT    NOT NULL,
    prompts_json        TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    total_documents     INTEGER NOT NULL,
    error               TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_documents (
    evaluation_id INTEGER NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    document      TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    error         TEXT,
    elapsed_ms    INTEGER,
    PRIMARY KEY (evaluation_id, document)
);

CREATE TABLE IF NOT EXISTS evaluation_items (
    evaluation_id INTEGER NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    document      TEXT    NOT NULL,
    entity        TEXT    NOT NULL,
    expected_json TEXT    NOT NULL,
    actual_json   TEXT    NOT NULL,
    confidence    TEXT    NOT NULL,
    matched       INTEGER NOT NULL,
    PRIMARY KEY (evaluation_id, document, entity)
);
"""

TERMINAL_STATUSES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class EvaluationItem:
    entity: str
    expected: Any
    actual: Any
    confidence: str
    matched: bool


@dataclass(frozen=True)
class EvaluationDocument:
    name: str
    status: str
    error: str | None
    elapsed_ms: int | None
    items: list[EvaluationItem]


@dataclass(frozen=True)
class EvaluationSummary:
    id: int
    created_at: str
    finished_at: str | None
    dataset: str
    model: str
    status: str
    total_documents: int
    completed_documents: int
    error: str | None
    metrics: EvaluationMetrics


@dataclass(frozen=True)
class EvaluationDetail(EvaluationSummary):
    prompts: PromptConfiguration = None  # type: ignore[assignment]
    documents: list[EvaluationDocument] = None  # type: ignore[assignment]

    @property
    def failures(self) -> list[tuple[str, str]]:
        return [
            (document.name, document.error or "")
            for document in self.documents
            if document.status == "failed"
        ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EvaluationStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def start(
        self,
        *,
        dataset: str,
        model: str,
        prompts: PromptConfiguration,
        total_documents: int,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO evaluations (created_at, dataset, model, prompts_json, status, total_documents)
                VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (
                    _now(),
                    dataset,
                    model,
                    json.dumps(prompts.model_dump(mode="json"), ensure_ascii=False),
                    total_documents,
                ),
            )
            return int(cursor.lastrowid)

    def record_document(
        self,
        evaluation_id: int,
        document: str,
        outcomes: list[FieldOutcome],
        elapsed_ms: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_documents (evaluation_id, document, status, elapsed_ms)
                VALUES (?, ?, 'ok', ?)
                ON CONFLICT(evaluation_id, document) DO UPDATE
                    SET status = 'ok', elapsed_ms = excluded.elapsed_ms, error = NULL
                """,
                (evaluation_id, document, elapsed_ms),
            )
            connection.executemany(
                """
                INSERT INTO evaluation_items
                    (evaluation_id, document, entity, expected_json, actual_json, confidence, matched)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_id, document, entity) DO UPDATE SET
                    expected_json = excluded.expected_json,
                    actual_json = excluded.actual_json,
                    confidence = excluded.confidence,
                    matched = excluded.matched
                """,
                [
                    (
                        evaluation_id,
                        document,
                        outcome.entity,
                        json.dumps(outcome.expected, ensure_ascii=False),
                        json.dumps(outcome.actual, ensure_ascii=False),
                        outcome.confidence,
                        int(outcome.matched),
                    )
                    for outcome in outcomes
                ],
            )

    def record_document_failure(self, evaluation_id: int, document: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_documents (evaluation_id, document, status, error)
                VALUES (?, ?, 'failed', ?)
                ON CONFLICT(evaluation_id, document) DO UPDATE
                    SET status = 'failed', error = excluded.error
                """,
                (evaluation_id, document, error),
            )

    def finish(self, evaluation_id: int, status: str, error: str | None = None) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"{status!r} is not a terminal evaluation status")
        with self._connect() as connection:
            connection.execute(
                "UPDATE evaluations SET status = ?, finished_at = ?, error = ? WHERE id = ?",
                (status, _now(), error, evaluation_id),
            )

    def mark_interrupted(self) -> int:
        """Close runs left `running` by a backend that stopped mid-evaluation."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE evaluations
                SET status = 'failed', finished_at = ?, error = 'Interrupted by a backend restart'
                WHERE status = 'running'
                """,
                (_now(),),
            )
            return cursor.rowcount

    def list_evaluations(self, limit: int = 50) -> list[EvaluationSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM evaluations ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._summary(connection, row) for row in rows]

    def get_evaluation(self, evaluation_id: int) -> EvaluationDetail | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)
            ).fetchone()
            if row is None:
                return None
            summary = self._summary(connection, row)
            documents = connection.execute(
                "SELECT * FROM evaluation_documents WHERE evaluation_id = ? ORDER BY document",
                (evaluation_id,),
            ).fetchall()
            items = connection.execute(
                "SELECT * FROM evaluation_items WHERE evaluation_id = ? ORDER BY document, entity",
                (evaluation_id,),
            ).fetchall()

        by_document: dict[str, list[EvaluationItem]] = {}
        for item in items:
            by_document.setdefault(item["document"], []).append(
                EvaluationItem(
                    entity=item["entity"],
                    expected=json.loads(item["expected_json"]),
                    actual=json.loads(item["actual_json"]),
                    confidence=item["confidence"],
                    matched=bool(item["matched"]),
                )
            )

        return EvaluationDetail(
            **{key: getattr(summary, key) for key in EvaluationSummary.__dataclass_fields__},
            prompts=PromptConfiguration.model_validate(json.loads(row["prompts_json"])),
            documents=[
                EvaluationDocument(
                    name=document["document"],
                    status=document["status"],
                    error=document["error"],
                    elapsed_ms=document["elapsed_ms"],
                    items=by_document.get(document["document"], []),
                )
                for document in documents
            ],
        )

    @staticmethod
    def _summary(connection: sqlite3.Connection, row: sqlite3.Row) -> EvaluationSummary:
        completed = connection.execute(
            "SELECT COUNT(*) AS n FROM evaluation_documents WHERE evaluation_id = ?",
            (row["id"],),
        ).fetchone()["n"]
        items = connection.execute(
            "SELECT entity, confidence, matched FROM evaluation_items WHERE evaluation_id = ?",
            (row["id"],),
        ).fetchall()
        outcomes = [
            FieldOutcome(
                entity=item["entity"],
                expected=None,
                actual=None,
                confidence=item["confidence"],
                matched=bool(item["matched"]),
            )
            for item in items
        ]
        return EvaluationSummary(
            id=row["id"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            dataset=row["dataset"],
            model=row["model"],
            status=row["status"],
            total_documents=row["total_documents"],
            completed_documents=completed,
            error=row["error"],
            metrics=aggregate(outcomes),
        )
