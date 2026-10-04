# 0006 — Experiments compare cells on shared documents, with paired intervals

**Context.** Two runs' headline accuracies differ for reasons other than the
configuration: one failed on documents the other scored, and a mean over a
handful of documents hides its spread.

**Decision.** An experiment is a grid of ordinary runs. Cells are compared only
on the documents every finished cell scored, each with a 95% bootstrap interval
over documents, and each difference from the best resampled on the same
documents for both cells (2,000 resamples, fixed seed). A cell is "worse" only
when the whole difference interval is below zero.

**Alternatives.** Ranking by point estimates — rejected: it turns noise into a
ranking on small datasets.

**Consequences.** Small datasets often answer "not distinguishable", which is
the honest answer.
