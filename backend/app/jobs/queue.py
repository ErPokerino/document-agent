"""Where a recorded job is run: in this process, or as a Cloud Run job execution.

Both take a job id and nothing else; everything the work needs is in its row
(`app.jobs.store`). In process is the default and what a developer machine
uses. On Cloud Run, a job execution of the backend image runs the work in its
own container (`python -m app.worker <id>`), billed while it runs, so the API
can scale to zero between requests without stopping a Lab run. Another
platform's batch service — AWS Batch, Azure Container Apps jobs, a Kubernetes
Job — is another class here with the same two methods.
"""

import asyncio
from typing import Any

import httpx

from app import config
from app.services.errors import ProviderError


class JobDispatchError(ProviderError):
    """The work was recorded but nothing could be started to do it."""


class InProcessJobs:
    """The work runs as a task of this event loop."""

    remote = False

    def __init__(self) -> None:
        self.tasks: dict[int, asyncio.Task[Any]] = {}

    async def dispatch(self, job_id: int) -> None:
        from app.jobs.runner import execute

        task = asyncio.create_task(execute(job_id))
        self.tasks[job_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job_id, None))

    def cancel(self, job_id: int) -> None:
        """Stop at once rather than at the next check, so a slow request does not run on."""
        task = self.tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()


class CloudRunJobs:
    """The work runs in an execution of a Cloud Run job, given the job id as its argument."""

    remote = True

    def __init__(self, job: str) -> None:
        if not job.startswith("projects/") or "/jobs/" not in job:
            raise ValueError("DOCUFLOW_JOBS_CLOUD_RUN_JOB must be projects/<project>/locations/<region>/jobs/<name>")
        self.job = job

    async def dispatch(self, job_id: int) -> None:
        from app.services import gcp_runtime

        token = await gcp_runtime.access_token()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"https://run.googleapis.com/v2/{self.job}:run",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"overrides": {"containerOverrides": [{"args": [str(job_id)]}]}},
                )
        except httpx.HTTPError as exc:
            raise JobDispatchError(f"Cloud Run did not answer the request to start job {job_id}: {exc}") from exc
        if response.status_code >= 300:
            raise JobDispatchError(
                f"Cloud Run refused to start job {job_id} ({response.status_code}): {response.text[:300]}"
            )

    def cancel(self, job_id: int) -> None:
        # The worker reads the request from the job's row within seconds.
        return None


def from_config() -> InProcessJobs | CloudRunJobs:
    backend = config.jobs_backend()
    if backend == "in_process":
        return InProcessJobs()
    if backend == "cloud_run":
        return CloudRunJobs(config.cloud_run_job())
    raise ValueError(f"DOCUFLOW_JOBS={backend!r} is not one of: in_process, cloud_run")
