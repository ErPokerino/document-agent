# Decision records

One file per decision that had real alternatives: what was decided, what was
rejected, and what follows from it. Numbered in the order they were made; a
record is never rewritten — a later one supersedes it and says so.

| # | Decision | Status |
|---|---|---|
| [0001](0001-pipelines-are-checked-steps.md) | Pipelines are ordered steps with declared contracts, checked before they run | Accepted |
| [0002](0002-lab-runs-snapshot-their-inputs.md) | A Lab run snapshots everything it ran with | Accepted |
| [0003](0003-candidates-and-resolution.md) | Steps propose candidates; a strategy chooses | Accepted |
| [0004](0004-models-stored-as-data.md) | Trained models are stored as data, never as pickles | Accepted |
| [0005](0005-local-first-cloud-portable.md) | Local first, deployable on any cloud | Accepted; supersedes "never deployed" |
| [0006](0006-experiments-compare-shared-documents.md) | Experiments compare cells on shared documents, with paired intervals | Accepted |
| [0007](0007-long-work-as-recorded-jobs.md) | Long work is a recorded job, run in process or by a worker elsewhere | Accepted |

To add one, copy the shape of an existing record: *Context*, *Decision*,
*Alternatives*, *Consequences*.
