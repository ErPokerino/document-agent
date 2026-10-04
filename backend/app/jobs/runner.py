"""Do one recorded job, wherever this runs: the API process or a worker.

The work for each kind lives beside the endpoint that asks for it; this module
only looks it up, keeps the row's status honest, and turns a request to stop —
written to the row by the API, possibly from another machine — into the same
cancellation the work already handles.
"""

import asyncio
import importlib
from typing import Any, Awaitable, Callable

from app.jobs.store import Job

# Read often enough that Cancel feels immediate, rarely enough to cost nothing.
CANCEL_POLL_SECONDS = 2.0

HANDLERS = {
    "evaluation": "app.api.routes.evaluations:run_evaluation_job",
    "experiment": "app.api.routes.experiments:run_experiment_job",
    "training": "app.api.routes.training:run_training_job",
    "fine_tuning_export": "app.api.routes.training:run_export_job",
}


def handler(kind: str) -> Callable[[Job, asyncio.Event], Awaitable[None]]:
    target = HANDLERS.get(kind)
    if target is None:
        raise ValueError(f"No handler for jobs of kind {kind!r}")
    module, name = target.split(":")
    return getattr(importlib.import_module(module), name)


async def _watch(job_id: int, cancelled: asyncio.Event, work: asyncio.Task[Any]) -> None:
    from app.api import deps

    while not work.done():
        await asyncio.sleep(CANCEL_POLL_SECONDS)
        if await asyncio.to_thread(deps.job_store.cancel_requested, job_id):
            cancelled.set()
            work.cancel()
            return


async def execute(job_id: int) -> None:
    from app.api import deps

    job = deps.job_store.get(job_id)
    if job is None or job.status != "running":
        return
    if job.cancel_requested:
        deps.job_store.finish(job_id, "cancelled")
        return
    deps.job_store.started(job_id)
    cancelled = asyncio.Event()
    work = asyncio.create_task(handler(job.kind)(job, cancelled))
    watcher = asyncio.create_task(_watch(job_id, cancelled, work))
    try:
        await work
        deps.job_store.finish(job_id, "cancelled" if cancelled.is_set() else "completed")
    except asyncio.CancelledError:
        deps.job_store.finish(job_id, "cancelled")
        # Cancelled from outside (the in-process queue): the work goes too.
        if not work.done():
            work.cancel()
    except Exception as exc:  # noqa: BLE001 - a job must never end silently
        deps.job_store.finish(job_id, "failed", error=str(exc) or type(exc).__name__)
    finally:
        watcher.cancel()
