"""Training runs in flight, and how the last ones ended.

Kept in memory: a training run reads every document of its datasets and can
take minutes, so it runs in the background and is polled, but what it leaves
behind that matters — the artefact — is on disk. A backend restart forgets the
jobs, never the models they produced.
"""

import asyncio
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# The latest ones are enough to see what just happened.
KEPT_JOBS = 20


@dataclass
class TrainingJob:
    id: int
    kind: str
    name: str
    created_at: str
    status: str = "running"
    total: int = 0
    done: int = 0
    artifact_id: str | None = None
    error: str | None = None
    skipped: list[str] = field(default_factory=list)
    # The file an export job wrote, under the exports folder.
    output: str | None = None
    examples: int = 0
    task: asyncio.Task[Any] | None = None
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)


class TrainingJobs:
    def __init__(self) -> None:
        self._jobs: dict[int, TrainingJob] = {}
        self._ids = itertools.count(1)

    def running(self) -> TrainingJob | None:
        return next((job for job in self._jobs.values() if job.status == "running"), None)

    def start(self, kind: str, name: str) -> TrainingJob:
        job = TrainingJob(
            id=next(self._ids), kind=kind, name=name,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._jobs[job.id] = job
        for stale in sorted(self._jobs)[:-KEPT_JOBS]:
            if self._jobs[stale].status != "running":
                del self._jobs[stale]
        return job

    def get(self, job_id: int) -> TrainingJob | None:
        return self._jobs.get(job_id)

    def all(self) -> list[TrainingJob]:
        return sorted(self._jobs.values(), key=lambda job: job.id, reverse=True)
