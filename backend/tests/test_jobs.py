"""Long work as recorded jobs: run here or by a worker elsewhere, stopped from either side."""

import asyncio
import json

import httpx
import pytest

from app import config
from app.api import deps
from app.jobs import runner
from app.jobs.queue import CloudRunJobs, InProcessJobs, JobDispatchError, from_config
from app.jobs.store import JobStore


@pytest.fixture
def store(tmp_path, monkeypatch) -> JobStore:
    jobs = JobStore(tmp_path / "jobs.db")
    monkeypatch.setattr(deps, "job_store", jobs)
    return jobs


def test_a_job_is_running_from_the_moment_it_is_asked_for(store) -> None:
    job = store.create("training", "Suppliers", {"algorithm": "knn_tfidf"}, total=4)

    assert job.status == "running"
    assert job.started_at is None
    assert job.payload == {"algorithm": "knn_tfidf"}
    assert store.active(("training",)).id == job.id


def test_progress_is_recorded_until_the_job_ends_and_not_after(store) -> None:
    job = store.create("training", "Suppliers", {})
    store.progress(job.id, done=2, phase="reading", skipped=["a.pdf: unreadable"])
    store.finish(job.id, "cancelled")
    store.progress(job.id, done=3)
    store.finish(job.id, "completed")

    finished = store.get(job.id)
    assert (finished.status, finished.done, finished.phase, finished.skipped) == ("cancelled", 2, None, ["a.pdf: unreadable"])
    assert store.active(("training",)) is None


def test_only_progress_fields_can_be_reported(store) -> None:
    job = store.create("training", "Suppliers", {})
    with pytest.raises(ValueError):
        store.progress(job.id, status="completed")


def test_the_latest_job_for_a_run_is_found_by_its_subject(store) -> None:
    store.create("evaluation", "first", {}, subject_id=7)
    second = store.create("evaluation", "retry", {}, subject_id=7)

    assert store.for_subject("evaluation", 7).id == second.id
    assert store.for_subject("experiment", 7) is None


def test_jobs_left_running_by_a_stopped_process_are_closed(store) -> None:
    job = store.create("evaluation", "run", {})

    assert store.mark_interrupted() == 1
    assert store.get(job.id).status == "failed"


@pytest.mark.asyncio
async def test_the_runner_does_the_work_and_records_how_it_ended(store, monkeypatch) -> None:
    seen = []

    async def work(job, cancelled):
        seen.append(job.payload["value"])

    async def broken(job, cancelled):
        raise ValueError("No such dataset")

    monkeypatch.setattr(runner, "handler", lambda kind: work if kind == "good" else broken)
    good = store.create("good", "ok", {"value": 3})
    bad = store.create("bad", "fails", {})

    await runner.execute(good.id)
    await runner.execute(bad.id)

    assert seen == [3]
    assert store.get(good.id).status == "completed"
    assert store.get(good.id).started_at is not None
    assert (store.get(bad.id).status, store.get(bad.id).error) == ("failed", "No such dataset")


@pytest.mark.asyncio
async def test_a_stop_requested_through_the_row_reaches_work_running_elsewhere(store, monkeypatch) -> None:
    """A worker on another machine learns of Cancel only from the database."""
    monkeypatch.setattr(runner, "CANCEL_POLL_SECONDS", 0.01)
    interrupted = asyncio.Event()

    async def slow(job, cancelled):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise

    monkeypatch.setattr(runner, "handler", lambda kind: slow)
    job = store.create("slow", "waits", {})
    execution = asyncio.create_task(runner.execute(job.id))
    await asyncio.sleep(0.05)
    store.request_cancel(job.id)
    await asyncio.wait_for(execution, 2)

    assert interrupted.is_set()
    assert store.get(job.id).status == "cancelled"


@pytest.mark.asyncio
async def test_a_job_cancelled_before_a_worker_started_it_is_not_run(store, monkeypatch) -> None:
    called = []

    async def work(job, cancelled):
        called.append(job.id)

    monkeypatch.setattr(runner, "handler", lambda kind: work)
    job = store.create("good", "queued", {})
    store.request_cancel(job.id)

    await runner.execute(job.id)

    assert called == []
    assert store.get(job.id).status == "cancelled"


def test_the_worker_runs_the_job_named_on_its_command_line(store, monkeypatch, capsys) -> None:
    from app import worker

    async def work(job, cancelled):
        store.progress(job.id, output="done.jsonl")

    monkeypatch.setattr(runner, "handler", lambda kind: work)
    job = store.create("good", "export", {})

    assert worker.main([str(job.id)]) == 0
    assert store.get(job.id).output == "done.jsonl"
    assert "ended completed" in capsys.readouterr().out
    assert worker.main(["not-a-number"]) == 2


@pytest.mark.asyncio
async def test_a_cloud_run_execution_is_started_with_the_job_id(monkeypatch) -> None:
    from app.services import gcp_runtime

    sent = {}

    async def token() -> str:
        return "token-from-metadata"

    async def post(self, url, headers=None, json=None):
        sent.update(url=url, headers=headers, body=json)
        return httpx.Response(200, json={"name": "operations/1"})

    monkeypatch.setattr(gcp_runtime, "access_token", token)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    jobs = CloudRunJobs("projects/p/locations/europe-west1/jobs/docuflow-worker")

    await jobs.dispatch(42)

    assert sent["url"] == "https://run.googleapis.com/v2/projects/p/locations/europe-west1/jobs/docuflow-worker:run"
    assert sent["headers"]["Authorization"] == "Bearer token-from-metadata"
    assert sent["body"] == {"overrides": {"containerOverrides": [{"args": ["42"]}]}}


@pytest.mark.asyncio
async def test_a_refused_cloud_run_execution_is_reported(monkeypatch) -> None:
    from app.services import gcp_runtime

    async def token() -> str:
        return "t"

    async def post(self, url, headers=None, json=None):
        return httpx.Response(403, text="Permission denied on run.jobs.runWithOverrides")

    monkeypatch.setattr(gcp_runtime, "access_token", token)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    with pytest.raises(JobDispatchError, match="403"):
        await CloudRunJobs("projects/p/locations/r/jobs/w").dispatch(1)


def test_the_job_backend_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.delenv("DOCUFLOW_JOBS", raising=False)
    assert isinstance(from_config(), InProcessJobs)
    monkeypatch.setenv("DOCUFLOW_JOBS", "cloud_run")
    monkeypatch.setenv("DOCUFLOW_JOBS_CLOUD_RUN_JOB", "projects/p/locations/r/jobs/w")
    assert from_config().remote
    monkeypatch.setenv("DOCUFLOW_JOBS_CLOUD_RUN_JOB", "docuflow-worker")
    with pytest.raises(ValueError):
        from_config()
    monkeypatch.setenv("DOCUFLOW_JOBS", "batch")
    with pytest.raises(ValueError):
        from_config()


def test_with_a_remote_worker_the_lab_is_busy_while_a_lab_job_runs(store, monkeypatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr(deps, "jobs", CloudRunJobs("projects/p/locations/r/jobs/w"))
    deps.claim_lab()  # nothing running: allowed, and nothing held in this process
    assert deps.active_model_operation is None

    store.create("experiment", "grid", {}, subject_id=1)
    with pytest.raises(HTTPException) as refused:
        deps.claim_lab()
    assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_a_job_that_cannot_be_dispatched_is_closed(store, monkeypatch) -> None:
    class Refusing:
        remote = True

        async def dispatch(self, job_id):
            raise JobDispatchError("Cloud Run refused")

    monkeypatch.setattr(deps, "jobs", Refusing())
    with pytest.raises(JobDispatchError):
        await deps.start_job("training", "t", {})

    (job,) = store.latest(("training",))
    assert (job.status, job.error) == ("failed", "Cloud Run refused")


def test_payloads_are_stored_as_json(store) -> None:
    job = store.create("training", "t", {"readers": [{"kind": "read_pdf_text", "config": {}}]})
    with deps.job_store._connect() as connection:
        raw = connection.execute("SELECT payload_json FROM jobs WHERE id = ?", (job.id,)).fetchone()[0]
    assert json.loads(raw)["readers"][0]["kind"] == "read_pdf_text"
    assert config.jobs_backend() in ("in_process", "cloud_run")
