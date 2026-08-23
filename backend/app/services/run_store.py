"""Durable history of every extraction and of the corrections a human made.

Two reasons this exists. It gives the app a history instead of losing every
result when the page is closed, and the corrections it captures are exactly the
ground truth an evaluation needs: a value a person looked at and signed off on.

All SQL lives in this class on purpose. Moving the history to a hosted database
later means reimplementing this one interface, not chasing queries through the
request handlers.
"""

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.domain.models import FieldExtraction, PromptConfiguration
from app.pipeline.definition import PipelineDefinition


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    filename        TEXT    NOT NULL,
    file_sha256     TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    page_count      INTEGER NOT NULL,
    processed_pages INTEGER NOT NULL,
    elapsed_ms      INTEGER NOT NULL,
    prompts_json    TEXT    NOT NULL,
    extraction_json TEXT    NOT NULL,
    source          TEXT    NOT NULL,
    provider        TEXT    NOT NULL DEFAULT 'lm_studio',
    pipeline        TEXT,
    steps           TEXT
);

CREATE TABLE IF NOT EXISTS run_corrections (
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    entity     TEXT    NOT NULL,
    value_json TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (run_id, entity)
);

CREATE INDEX IF NOT EXISTS runs_created_at ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS runs_file_sha256 ON runs(file_sha256);
"""


@dataclass(frozen=True)
class RunSummary:
    id: int
    created_at: str
    filename: str
    file_sha256: str
    model: str
    page_count: int
    processed_pages: int
    elapsed_ms: int
    source: str
    provider: str
    pipeline: str
    # What actually ran, in order, rather than only the name it ran under.
    steps: list[str]
    has_corrections: bool


@dataclass(frozen=True)
class RunDetail(RunSummary):
    prompts: PromptConfiguration = None  # type: ignore[assignment]
    extraction: dict[str, FieldExtraction] = None  # type: ignore[assignment]
    corrections: dict[str, Any] = None  # type: ignore[assignment]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # PDFs live beside the database, addressed by content hash: identical
        # files are stored once, and the database stays small enough to copy.
        self.documents_dir = self.path.parent / "documents"
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            existing = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
            if "provider" not in existing:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN provider TEXT NOT NULL DEFAULT 'lm_studio'"
                )
            if "pipeline" not in existing:
                # Nullable on purpose: a run from before pipelines existed has no
                # honest answer, and reads back as the default pipeline.
                connection.execute("ALTER TABLE runs ADD COLUMN pipeline TEXT")
            if "steps" not in existing:
                connection.execute("ALTER TABLE runs ADD COLUMN steps TEXT")

    def read_document(self, file_sha256: str) -> bytes | None:
        path = self._document_path(file_sha256)
        return path.read_bytes() if path.exists() else None

    def _document_path(self, file_sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", file_sha256):
            raise ValueError("A document is addressed by its sha256 hex digest")
        return self.documents_dir / f"{file_sha256}.pdf"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # One connection per operation: sqlite3 connections are not safe to
        # share between threads, and these operations are short.
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def record_run(
        self,
        *,
        filename: str,
        content: bytes,
        model: str,
        prompts: PromptConfiguration,
        extraction: dict[str, FieldExtraction],
        page_count: int,
        processed_pages: int,
        elapsed_ms: int,
        source: str = "workspace",
        provider: str = "lm_studio",
        pipeline: str | None = None,
        steps: list[str] | None = None,
    ) -> int:
        serialized = {
            name: field.model_dump(mode="json") for name, field in extraction.items()
        }
        digest = hashlib.sha256(content).hexdigest()
        document_path = self._document_path(digest)
        if not document_path.exists():
            document_path.write_bytes(content)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO runs (created_at, filename, file_sha256, model, page_count,
                                  processed_pages, elapsed_ms, prompts_json, extraction_json,
                                  source, provider, pipeline, steps)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _now(),
                    filename,
                    digest,
                    model,
                    page_count,
                    processed_pages,
                    elapsed_ms,
                    json.dumps(prompts.model_dump(mode="json"), ensure_ascii=False),
                    json.dumps(serialized, ensure_ascii=False),
                    source,
                    provider,
                    pipeline or PipelineDefinition.default().name,
                    ",".join(steps or []),
                ),
            )
            return int(cursor.lastrowid)

    def record_corrections(self, run_id: int, corrections: dict[str, Any]) -> None:
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone()
            if exists is None:
                raise ValueError(f"No run with id {run_id}")
            connection.executemany(
                """
                INSERT INTO run_corrections (run_id, entity, value_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, entity) DO UPDATE
                    SET value_json = excluded.value_json, created_at = excluded.created_at
                """,
                [
                    (run_id, entity, json.dumps(value, ensure_ascii=False), _now())
                    for entity, value in corrections.items()
                ],
            )

    def list_runs(self, limit: int = 50, offset: int = 0, validated_only: bool = False) -> list[RunSummary]:
        having = "HAVING COUNT(c.entity) > 0" if validated_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT r.*, COUNT(c.entity) AS correction_count
                FROM runs r
                LEFT JOIN run_corrections c ON c.run_id = r.id
                GROUP BY r.id
                {having}
                ORDER BY r.id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get_run(self, run_id: int) -> RunDetail | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT r.*, COUNT(c.entity) AS correction_count
                FROM runs r
                LEFT JOIN run_corrections c ON c.run_id = r.id
                WHERE r.id = ?
                GROUP BY r.id
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            corrections = connection.execute(
                "SELECT entity, value_json FROM run_corrections WHERE run_id = ?", (run_id,)
            ).fetchall()

        summary = self._summary(row)
        return RunDetail(
            **{key: getattr(summary, key) for key in RunSummary.__dataclass_fields__},
            prompts=PromptConfiguration.model_validate(json.loads(row["prompts_json"])),
            extraction={
                name: FieldExtraction.model_validate(payload)
                for name, payload in json.loads(row["extraction_json"]).items()
            },
            corrections={
                correction["entity"]: json.loads(correction["value_json"])
                for correction in corrections
            },
        )

    def validated_values(self, run_id: int) -> dict[str, Any] | None:
        """What a human signed off on: corrections layered over the extraction."""
        run = self.get_run(run_id)
        if run is None:
            return None
        return {
            name: run.corrections.get(name, field.value)
            for name, field in run.extraction.items()
        } | {name: value for name, value in run.corrections.items() if name not in run.extraction}

    @staticmethod
    def _summary(row: sqlite3.Row) -> RunSummary:
        return RunSummary(
            id=row["id"],
            created_at=row["created_at"],
            filename=row["filename"],
            file_sha256=row["file_sha256"],
            model=row["model"],
            page_count=row["page_count"],
            processed_pages=row["processed_pages"],
            elapsed_ms=row["elapsed_ms"],
            source=row["source"],
            provider=row["provider"],
            pipeline=row["pipeline"] or PipelineDefinition.default().name,
            steps=[step for step in (row["steps"] or "").split(",") if step],
            has_corrections=bool(row["correction_count"]),
        )
