"""An experiment: several configurations over one dataset, compared on the same documents.

A Lab run answers "how well does this configuration do". Comparing two of them
by their headline numbers mixes in everything else that differed: one run may
have failed on three documents the other scored, and each figure is a mean over
a handful of documents whose spread nobody sees.

An experiment is a plan of cells — pipelines down the side, models across the
top — and every cell is an ordinary Lab run, with the same snapshot, pinning
and fingerprint. The comparison is then made only on the documents every
finished cell scored, and each accuracy carries a bootstrap interval over those
documents. A difference from the best cell is resampled on the same documents
for both cells (a paired bootstrap), which is what makes a small difference on
a small dataset readable as "not distinguishable" rather than as a ranking.
"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from app.domain.models import MODEL_NOT_USED
from app.pipeline.definition import PipelineDefinition, requires_vision, uses_model
from app.services import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    finished_at     TEXT,
    name            TEXT    NOT NULL,
    dataset         TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    reuse_readings  INTEGER NOT NULL DEFAULT 0,
    cells_json      TEXT    NOT NULL,
    error           TEXT
);
"""

# Enough resamples for a stable 95% interval on the second decimal, few
# enough to compute on every request for datasets of this size.
RESAMPLES = 2000
# Fixed, so the same runs always show the same interval.
SEED = 20261004


@dataclass
class ModelChoice:
    provider: str
    model: str
    # False only when the model is known not to read images.
    vision: bool = True


@dataclass
class Cell:
    pipeline: str
    provider: str
    model: str
    # Why the cell is in the plan but will not run.
    skipped: str | None = None
    # Why a cell that was to run did not produce a run.
    error: str | None = None
    # Set while the driver loads the cell's model or runs it.
    phase: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline, "provider": self.provider, "model": self.model,
            "skipped": self.skipped, "error": self.error, "phase": self.phase,
        }


def plan_cells(pipelines: list[PipelineDefinition], models: list[ModelChoice]) -> list[Cell]:
    """Every pipeline with every model, as the grid shows them.

    A pipeline that calls no model is one cell, whatever models were chosen:
    running it once per model would measure the same thing several times. A
    pipeline that hands page images to the model is not paired with a model
    known not to read them; the cell stays in the grid and says why.
    """
    cells: list[Cell] = []
    for pipeline in pipelines:
        if not uses_model(pipeline):
            cells.append(Cell(pipeline.name, "none", MODEL_NOT_USED))
            continue
        for choice in models:
            cell = Cell(pipeline.name, choice.provider, choice.model)
            if requires_vision(pipeline) and not choice.vision:
                cell.skipped = "This pipeline gives the model page images, and this model does not read images."
            cells.append(cell)
    return cells


def execution_order(cells: list[Cell]) -> list[int]:
    """Cells that run, grouped by model, so each local model is loaded once."""
    runnable = [index for index, cell in enumerate(cells) if cell.skipped is None]
    return sorted(runnable, key=lambda index: (cells[index].provider != "none", cells[index].provider, cells[index].model, index))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class StoredExperiment:
    id: int
    created_at: str
    finished_at: str | None
    name: str
    dataset: str
    status: str
    reuse_readings: bool
    cells: list[Cell]
    error: str | None


class ExperimentStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        db.prepare(self.path)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with db.connect(self.path) as connection:
            yield connection

    def create(self, *, name: str, dataset: str, cells: list[Cell], reuse_readings: bool) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO experiments (created_at, name, dataset, status, reuse_readings, cells_json) VALUES (?, ?, ?, 'running', ?, ?)",
                (_now(), name, dataset, int(reuse_readings), json.dumps([cell.as_dict() for cell in cells], ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def _row(self, row: sqlite3.Row) -> StoredExperiment:
        return StoredExperiment(
            id=row["id"], created_at=row["created_at"], finished_at=row["finished_at"], name=row["name"],
            dataset=row["dataset"], status=row["status"], reuse_readings=bool(row["reuse_readings"]),
            cells=[Cell(**cell) for cell in json.loads(row["cells_json"])], error=row["error"],
        )

    def get(self, experiment_id: int) -> StoredExperiment | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        return self._row(row) if row else None

    def list(self) -> list[StoredExperiment]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM experiments ORDER BY id DESC").fetchall()
        return [self._row(row) for row in rows]

    def update_cell(self, experiment_id: int, index: int, **changes: Any) -> None:
        with self._connect() as connection:
            row = connection.execute("SELECT cells_json FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
            if row is None:
                return
            cells = json.loads(row["cells_json"])
            cells[index].update(changes)
            connection.execute("UPDATE experiments SET cells_json = ? WHERE id = ?", (json.dumps(cells, ensure_ascii=False), experiment_id))

    def finish(self, experiment_id: int, status: str, error: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE experiments SET status = ?, finished_at = ?, error = ? WHERE id = ? AND status = 'running'",
                (status, _now(), error, experiment_id),
            )

    def delete(self, experiment_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM experiments WHERE id = ?", (experiment_id,))

    def mark_interrupted(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE experiments SET status = 'failed', finished_at = ?, error = 'Interrupted by a backend restart' WHERE status = 'running'",
                (_now(),),
            )


# -- comparison ----------------------------------------------------------------------


@dataclass
class CellScore:
    cell: int
    accuracy: float
    low: float
    high: float
    delta: float
    delta_low: float
    delta_high: float
    # "best", "worse" when the whole interval of the difference is below zero,
    # "indistinguishable" otherwise.
    verdict: str
    seconds_per_document: float | None
    per_entity: dict[str, float | None] = field(default_factory=dict)


@dataclass
class Comparison:
    shared_documents: list[str]
    # Documents some finished cell did not score, and so left out of every cell.
    left_out: list[str]
    resamples: int
    cells: list[CellScore]


def compare(runs: dict[int, Any], *, resamples: int = RESAMPLES, seed: int = SEED) -> Comparison | None:
    """Accuracy with a 95% interval per cell, on the documents every cell scored.

    `runs` maps a cell index to its evaluation detail. Only runs that scored at
    least one document take part; a cell that failed outright has nothing to
    compare and is shown by its status instead.
    """
    usable = {
        index: detail for index, detail in runs.items()
        if any(document.status == "ok" for document in detail.documents)
    }
    if not usable:
        return None
    scored = [
        {document.name for document in detail.documents if document.status == "ok"}
        for detail in usable.values()
    ]
    everyone = set.union(*scored)
    shared = sorted(set.intersection(*scored))
    if not shared:
        return Comparison(shared_documents=[], left_out=sorted(everyone), resamples=resamples, cells=[])

    order = list(usable)
    matched = np.zeros((len(order), len(shared)))
    totals = np.zeros((len(order), len(shared)))
    seconds: dict[int, float | None] = {}
    per_entity: dict[int, dict[str, float | None]] = {}
    for row, index in enumerate(order):
        by_name = {document.name: document for document in usable[index].documents}
        tallies: dict[str, list[int]] = {}
        elapsed = []
        for column, name in enumerate(shared):
            document = by_name[name]
            matched[row, column] = sum(item.matched for item in document.items)
            totals[row, column] = len(document.items)
            if document.elapsed_ms is not None:
                elapsed.append(document.elapsed_ms / 1000)
            for item in document.items:
                tally = tallies.setdefault(item.entity, [0, 0])
                tally[0] += int(item.matched)
                tally[1] += 1
        seconds[index] = float(np.mean(elapsed)) if elapsed else None
        per_entity[index] = {name: (right / total if total else None) for name, (right, total) in tallies.items()}

    def pooled(sample: np.ndarray) -> np.ndarray:
        right = matched[:, sample].sum(axis=-1)
        total = totals[:, sample].sum(axis=-1)
        return np.divide(right, total, out=np.zeros_like(right), where=total > 0)

    observed = pooled(np.arange(len(shared)))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(shared), size=(resamples, len(shared)))
    # One set of resamples for every cell: the difference between two cells is
    # measured on the same documents in each draw, which is the pairing.
    boot = np.stack([pooled(draw) for draw in draws])  # (resamples, cells)
    best = int(np.argmax(observed))
    differences = boot - boot[:, [best]]

    scores = []
    for row, index in enumerate(order):
        low, high = np.percentile(boot[:, row], [2.5, 97.5])
        delta_low, delta_high = np.percentile(differences[:, row], [2.5, 97.5])
        delta = float(observed[row] - observed[best])
        verdict = "best" if row == best else ("worse" if delta_high < 0 else "indistinguishable")
        scores.append(
            CellScore(
                cell=index, accuracy=float(observed[row]), low=float(low), high=float(high),
                delta=delta, delta_low=float(delta_low), delta_high=float(delta_high), verdict=verdict,
                seconds_per_document=seconds[index], per_entity=per_entity[index],
            )
        )
    scores.sort(key=lambda score: -score.accuracy)
    return Comparison(shared_documents=shared, left_out=sorted(everyone - set(shared)), resamples=resamples, cells=scores)
