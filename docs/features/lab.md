# Lab: runs, experiments and comparisons

Measuring a configuration over a labelled dataset, comparing configurations, and what each run records so it can be trusted later.

## Dataset integrity, retries and usage accounting

Uploading a PDF under an existing document name returns a conflict. It never
replaces the original or inherits its labels. Promoting several reviewed runs
checks names across the entire selection before writing any document.

Every new Lab evaluation stores its input manifest (names, content hashes and
labels) and keeps the original PDFs in `backend/data/evaluation-inputs`, deduplicated
by hash. Both its first execution and retries read those bytes. Adding documents,
editing labels, removing or renaming the source dataset no longer changes a retry.
The Lab preview also reads the snapshot. Evaluations predating this change remain
readable, but cannot be retried: their original input set cannot be reconstructed
reliably. New Lab runs pin Custom Extractor versions when metadata is available,
and snapshot the supplier register and supplier rules so a retry replays them.
Other remote processors remain mutable. Input files that no remaining evaluation
refers to are reclaimed after a grace period; a file just snapshotted is kept
until the run that names it is written.

Lab and reviewed-run selectors traverse cursor pages before filtering, comparing
or exporting, rather than silently using only the newest fifty records. For a
large history this reads all summaries; server-side filtering and aggregation
remain a future scalability improvement.

Supplier-rule model calls contribute their token counts. Custom Extractor pages
are persisted and exported alongside OCR/Layout usage, with an editable USD rate
per thousand pages in Settings. Its rate starts unset rather than assuming an
account's tariff. Costs are estimates at the configured rates, not invoices or
local hardware/energy costs. Missing rates or incomplete usage produce no total;
older runs, failed runs and resumed evaluations do not claim complete accounting
for calls that may have been billed without reporting usage. Recorded usage is
still available in CSV. A changed expected label is shown separately in the
run comparison and excluded from its net fixes/regressions.

## Stored Document AI readings

Every OCR and Layout Parser reading made by a step that names a **pinned
processor version** is kept in `backend/data/reading-cache`, keyed by the
original PDF, the number of pages sent, the processor and its version. A step
that calls a processor's default version has no key, because Google can move
the default and a stored reading would outlive the processor that made it. Lab
runs pin versions when metadata allows; Workspace runs pin only what the
pipeline names explicitly.

Storing is always on; reading back is a per-run choice in Lab (**Reuse stored
Document AI readings**), off by default. A run that reuses readings records it,
counts the reused pages as `cached_pages` rather than as OCR or layout pages,
and is left out of the time and cost figures in Analytics while still counting
for accuracy. A retry replays the choice its run started with. The cache is
also what training reads its corpus from.

## Lab navigation and extraction engines

Dataset, extraction engine, pipeline and LLM location filters support searchable
checkboxes, Select all, Clear selection and removable chips. Choices combine
with OR within a filter and AND between filters, and persist between Past runs
and Analytics. Past runs offers 10/25/50 rows per page, Previous/Next and direct
page selection. Export and Analytics use all matching runs, not just that page.

New Lab evaluations snapshot Custom Extractor display names, processor ids,
project/location, exact versions and base versions when exposed by Google.
Resolved versions are explicitly invoked and retained in the retry pipeline.
Metadata access failures retain unknown facts; historical records are never
filled with today's default. Additional LLMs are identified separately. A retry
with a different Google project/location is refused. Multiple extractor steps
are resolved and pinned independently. CSV includes the recorded identities.

Analytics groups runs that share a configuration fingerprint. Runs recorded
before a fingerprint existed still group by engine, pipeline and dataset.
Each chart can be saved as a PNG, and its values as a CSV: the comparison keeps
every resource column, with the Pareto flag for the axis on screen, and field
accuracy keeps the pooled counts. Charts use compact numbers linked to comparison rows and a
detail panel, with collision avoidance for labels. Tooltips omit dataset names
and duplicate reader names. Pareto rows have a subtle background and a badge,
recomputed for the selected axis; this is a trade-off frontier, not a universal
ranking. Field accuracy remains pooled across the selection as its help states.

The offered Gemini models are 3.8 Flash, 3.1 Pro Preview and 3.5 Flash Lite.
Saved 3.7 selections migrate to 3.8; historical runs retain 3.7 and its pricing.
New model prices are added without replacing customized rates. 3.8 Flash starts
at the standard introductory USD 0.75/3.75 per million input/output tokens,
checked on 2026-09-06. Pro's context-tiered pricing cannot be represented by the
current flat-rate calculator, so its rates start unset and its cost is unknown
until explicitly configured. Source: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Experiments

In Lab, **Run a test** starts either one configuration or an **Experiment**: a
grid with pipelines down the side and models across the top, over one dataset.
The builder shows the grid before anything runs — which cells run, which are
skipped and why, and how many document extractions that is. A pipeline that
calls no model is one cell whatever models are chosen; a pipeline that sends
page images is not paired with a model known not to read them.

Every cell is an ordinary Lab run, with its own snapshot, pinned processors and
fingerprint, listed in Past runs and in Analytics like any other. Cells run one
after another, grouped by model, so each local model is loaded once. The model
selected in LLM is not changed, though another one may be in memory when the
experiment ends. Cancelling the run in progress cancels the experiment.

A run and an experiment each run in the background as a recorded job, one at a
time: locally inside the backend, deployed in a worker of their own, so closing
the page or the app scaling down does not stop them
([deployment](../deployment.md#long-work-runs-as-jobs)). Cancel reaches the
work wherever it runs, within a few seconds.
Deleting an experiment forgets the grid; its runs stay.

The results grid shows each cell's accuracy, time and cost per document. Below
it, the cells are compared **only on the documents every finished cell
scored** — a document one cell failed on would otherwise count against the
other alone — with a 95% bootstrap interval over documents and, for each cell,
its difference from the best resampled on the same documents for both (a
paired bootstrap, 2,000 resamples, fixed seed). A cell whose difference
interval lies wholly below zero is *worse than the best*; otherwise it is *not
distinguishable from the best*, which says these documents cannot tell the two
apart, not that they are equal. Accuracy per field follows on the same
documents.
