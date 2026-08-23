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
from app.pipeline.definition import PipelineDefinition
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
    error               TEXT,
    max_pages           INTEGER NOT NULL DEFAULT 0,
    pipeline            TEXT,
    steps               TEXT
);

CREATE TABLE IF NOT EXISTS evaluation_documents (
    evaluation_id INTEGER NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    document      TEXT    NOT NULL,
    status            TEXT    NOT NULL,
    error             TEXT,
    elapsed_ms        INTEGER,
    prompt_tokens     INTEGER,
    ocr_pages         INTEGER,
    layout_pages      INTEGER,
    completion_tokens INTEGER,
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

# "partial" is its own outcome: a run that reached the model for only some
# of its documents must not be reported as if it had finished the job.
TERMINAL_STATUSES = ("completed", "partial", "failed", "cancelled")


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
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    ocr_pages: int | None = None
    layout_pages: int | None = None


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
    max_pages: int
    pipeline: str
    # What actually ran, in order. The pipeline name is a label and can be
    # edited or reused; this is the only record of the shape of the run.
    steps: list[str]
    succeeded_documents: int
    failed_documents: int
    pending_documents: int
    total_elapsed_ms: int
    average_elapsed_ms: int | None
    # Facts, not money: the price to apply to them is a setting, so cost is
    # derived at display time and a rate change carries history with it.
    prompt_tokens: int
    completion_tokens: int
    # Pages sent to Document AI, which is billed per page rather than per token.
    ocr_pages: int
    layout_pages: int
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
            self._add_missing_columns(connection)

    @staticmethod
    def _add_missing_columns(connection: sqlite3.Connection) -> None:
        """Bring a database created by an earlier version up to date."""
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(evaluations)")}
        if "max_pages" not in existing:
            connection.execute(
                "ALTER TABLE evaluations ADD COLUMN max_pages INTEGER NOT NULL DEFAULT 0"
            )
        if "pipeline" not in existing:
            # Nullable: a run started before pipelines existed ran the default one.
            connection.execute("ALTER TABLE evaluations ADD COLUMN pipeline TEXT")
        if "steps" not in existing:
            # A run from before this says nothing rather than claiming a shape.
            connection.execute("ALTER TABLE evaluations ADD COLUMN steps TEXT")

        document_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(evaluation_documents)")
        }
        for column in ("prompt_tokens", "completion_tokens", "ocr_pages", "layout_pages"):
            if column not in document_columns:
                connection.execute(
                    f"ALTER TABLE evaluation_documents ADD COLUMN {column} INTEGER"
                )

        # Runs finished before "partial" existed were all stored as "completed",
        # including ones where most documents never reached the model. Their
        # rows still hold the truth, so the status can be recomputed. Cancelled
        # and failed runs are left as they are.
        connection.execute(
            """
            UPDATE evaluations SET status = CASE
                WHEN (SELECT COUNT(*) FROM evaluation_documents d
                      WHERE d.evaluation_id = evaluations.id AND d.status = 'ok') = 0
                THEN 'failed' ELSE 'partial' END
            WHERE status = 'completed'
              AND (SELECT COUNT(*) FROM evaluation_documents d
                   WHERE d.evaluation_id = evaluations.id AND d.status = 'ok') < total_documents
            """
        )

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
        max_pages: int = 0,
        pipeline: str | None = None,
        steps: list[str] | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO evaluations
                    (created_at, dataset, model, prompts_json, status, total_documents,
                     max_pages, pipeline, steps)
                VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    _now(),
                    dataset,
                    model,
                    json.dumps(prompts.model_dump(mode="json"), ensure_ascii=False),
                    total_documents,
                    max_pages,
                    pipeline or PipelineDefinition.default().name,
                    ",".join(steps or []),
                ),
            )
            return int(cursor.lastrowid)

    def attempted_documents(self, evaluation_id: int) -> dict[str, str]:
        """Every document this run reached, and how it went."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document, status FROM evaluation_documents WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchall()
        return {row["document"]: row["status"] for row in rows}

    def complete(self, evaluation_id: int) -> str:
        """Finish a run with the status its documents actually earned."""
        outcomes = self.attempted_documents(evaluation_id).values()
        succeeded = sum(status == "ok" for status in outcomes)
        with self._connect() as connection:
            total = connection.execute(
                "SELECT total_documents FROM evaluations WHERE id = ?", (evaluation_id,)
            ).fetchone()["total_documents"]

        if succeeded == 0:
            status = "failed"
        elif succeeded < total:
            status = "partial"
        else:
            status = "completed"
        self.finish(evaluation_id, status)
        return status

    def reopen(self, evaluation_id: int) -> None:
        """Put a finished run back in flight so its gaps can be filled."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE evaluations SET status = 'running', finished_at = NULL, error = NULL WHERE id = ?",
                (evaluation_id,),
            )

    def delete(self, evaluation_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM evaluations WHERE id = ?", (evaluation_id,))
            # The child rows go with it through ON DELETE CASCADE.
            return cursor.rowcount > 0

    def record_document(
        self,
        evaluation_id: int,
        document: str,
        outcomes: list[FieldOutcome],
        elapsed_ms: int,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        ocr_pages: int | None = None,
        layout_pages: int | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_documents
                    (evaluation_id, document, status, elapsed_ms, prompt_tokens,
                     completion_tokens, ocr_pages, layout_pages)
                VALUES (?, ?, 'ok', ?, ?, ?, ?, ?)
                ON CONFLICT(evaluation_id, document) DO UPDATE SET
                    status = 'ok',
                    elapsed_ms = excluded.elapsed_ms,
                    prompt_tokens = excluded.prompt_tokens,
                    completion_tokens = excluded.completion_tokens,
                    ocr_pages = excluded.ocr_pages,
                    layout_pages = excluded.layout_pages,
                    error = NULL
                """,
                (
                    evaluation_id,
                    document,
                    elapsed_ms,
                    prompt_tokens,
                    completion_tokens,
                    ocr_pages,
                    layout_pages,
                ),
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
                "DELETE FROM evaluation_items WHERE evaluation_id = ? AND document = ?",
                (evaluation_id, document),
            )
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
                    prompt_tokens=document["prompt_tokens"],
                    completion_tokens=document["completion_tokens"],
                    ocr_pages=document["ocr_pages"],
                    layout_pages=document["layout_pages"],
                )
                for document in documents
            ],
        )

    @staticmethod
    def _summary(connection: sqlite3.Connection, row: sqlite3.Row) -> EvaluationSummary:
        progress = connection.execute(
            """
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END), 0) AS succeeded,
                   COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed,
                   COALESCE(SUM(elapsed_ms), 0) AS total_ms,
                   AVG(elapsed_ms) AS average_ms,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(ocr_pages), 0) AS ocr_pages,
                   COALESCE(SUM(layout_pages), 0) AS layout_pages
            FROM evaluation_documents WHERE evaluation_id = ?
            """,
            (row["id"],),
        ).fetchone()
        completed = progress["n"]
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
            max_pages=row["max_pages"],
            pipeline=row["pipeline"] or PipelineDefinition.default().name,
            steps=[step for step in (row["steps"] or "").split(",") if step],
            succeeded_documents=int(progress["succeeded"] or 0),
            failed_documents=int(progress["failed"] or 0),
            pending_documents=max(row["total_documents"] - completed, 0),
            total_elapsed_ms=int(progress["total_ms"] or 0),
            average_elapsed_ms=round(progress["average_ms"]) if progress["average_ms"] else None,
            prompt_tokens=int(progress["prompt_tokens"] or 0),
            completion_tokens=int(progress["completion_tokens"] or 0),
            ocr_pages=int(progress["ocr_pages"] or 0),
            layout_pages=int(progress["layout_pages"] or 0),
            metrics=aggregate(outcomes),
        )
