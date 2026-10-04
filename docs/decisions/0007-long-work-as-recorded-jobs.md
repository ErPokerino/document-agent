# 0007 — Long work is a recorded job, run in process or by a worker elsewhere

**Context.** Lab runs, experiments and training take minutes to hours. They ran
as tasks inside the API process, holding their state in memory. On a managed
platform that scales the API to zero between requests, or restarts it, that
killed the run; and keeping one instance always on to protect it costs more
than everything else in a small deployment together.

**Decision.** Each piece of long work is a row in a `jobs` table: its kind, a
JSON payload saying what to do, its progress, its outcome, and whether a stop
was requested. The API validates the request, records the run and the job, and
returns. A job runner then does the work: a task of the API's own event loop
(`in_process`, the default and what a developer machine uses), or a container
started for that one job (`cloud_run`: a Cloud Run job execution running
`python -m app.worker <id>`). The work rebuilds what it needs from the rows —
a Lab run from its snapshot ([0002](0002-lab-runs-snapshot-their-inputs.md)),
which is also how a retry already worked — and reports into them. Cancel writes
to the row; the work reads it every few seconds wherever it runs, and in
process the task is also cancelled at once.

**Alternatives.**
- *A queue service (Cloud Tasks, Pub/Sub, SQS) pushing to the API* — rejected
  for now: the API would have to stay up for the whole run, which is the
  problem being solved, and a request timeout caps how long it may take.
- *A long-lived worker pool polling the table* — rejected for a small
  deployment: it is always on and always billed. It remains a valid runner for
  a busy one, and needs no change to the jobs themselves.
- *Keeping work in process with one instance always on* — rejected on cost.

**Consequences.** The API no longer has to outlive a run. Progress and
cancellation go through the database, so they work across machines, at the
price of a write per document and a short delay before a stop is noticed.
A worker reads today's settings for what a run does not record (keys,
addresses). Another platform's batch service is one more runner class with
`dispatch` and `cancel`.
