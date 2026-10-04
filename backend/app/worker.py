"""Run one recorded job and exit: `python -m app.worker <job id>`.

The entry point of a Cloud Run job execution (or any batch container). It
opens the same stores the API does, from the same environment, does the work
the job's row describes, and leaves the outcome in that row.

`python -m app.worker migrate-sqlite <file>` instead copies a local SQLite
database into the configured PostgreSQL one (app.migrate_sqlite): run where
the database is reachable, which on Cloud Run is an execution of this job.
"""

import asyncio
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "migrate-sqlite":
        from app.migrate_sqlite import copy_sqlite

        copied = copy_sqlite(Path(argv[1]))
        print(f"Copied {sum(copied.values())} rows from {len(copied)} tables.")
        return 0
    if len(argv) != 1 or not argv[0].isdigit():
        print("usage: python -m app.worker <job id> | migrate-sqlite <file>", file=sys.stderr)
        return 2
    job_id = int(argv[0])

    from app.api import deps
    from app.jobs.runner import execute

    asyncio.run(execute(job_id))
    job = deps.job_store.get(job_id)
    if job is None:
        print(f"No job with id {job_id}", file=sys.stderr)
        return 1
    print(f"Job {job_id} ({job.kind}) ended {job.status}" + (f": {job.error}" if job.error else ""))
    # A failed job is recorded on its row; the execution itself did its part.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
