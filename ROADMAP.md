# Roadmap

What comes next, and work decided on but deliberately postponed, with the
reasoning that led there. Kept in the repository so the decisions outlive the
conversations that produced them. What is already built is described in
[docs/](docs/README.md); decisions with rejected alternatives are in
[docs/decisions/](docs/decisions/README.md).

## Next

In order. Each builds on the Lab and the model registry as they are now.

### 1. Trained models as an axis of an experiment

An experiment crosses pipelines with language models. A trained model is used
through a pipeline step, so comparing a nearest neighbour, LightGBM and an LLM
today means saving one pipeline per model. Let the grid take trained models as
columns too — the pipeline's Trained model step bound to each in turn — so
every approach to a field is compared on the same documents, with the same
paired intervals, in one experiment. A cell keeps being an ordinary run; its
pipeline snapshot records the model id it used.

### 2. Hyperparameter search

Every algorithm declares its parameters with bounds
(`backend/app/training/algorithms.py`). A search — a grid, or random samples
within the bounds — can train each candidate setting under the same grouped
cross-validation, keep the scores of all of them, and register the best as a
model, with the search recorded in its manifest. Two things to keep honest: the
score of the chosen setting is optimistic, because it won among many, so the
model's figure stays the cross-validated one and a Lab run on a separate dataset
remains the measurement; and the search space, not only the winner, belongs in
the record.

### 3. Experiments as recipes

An experiment's grid — pipelines, models, options — saved under a name and run
again on a new dataset with one action, and two experiments compared: the same
recipe on last month's and this month's documents, or two recipes on the same
dataset. A recipe stores names and model ids, so it says plainly when a
pipeline or model it names has changed or is gone since.

## Cloud deployment

The gaps in [docs/deployment.md](docs/deployment.md#what-is-not-portable-yet),
in the order a first deployment on Google Cloud meets them. Each is an
interface with the local implementation kept, never a GCP-only replacement.

1. **Access control** before anything is reachable: behind the platform's
   identity-aware proxy at first; users and roles in the app once more than one
   team works in it.
2. **Jobs out of the API process.** Lab runs, experiments and training behind
   one job interface: in-process locally, a queue (Cloud Tasks or Pub/Sub on
   GCP) when deployed. Until then, one instance.
3. **Credentials from the runtime.** Application Default Credentials for
   Document AI and Vertex AI on Google Cloud; the key file stays for other hosts.
4. **Database interface.** The SQLite stores behind one SQL layer that also runs
   on PostgreSQL (Cloud SQL, RDS, Azure Database).
5. **Storage interface.** Datasets, evaluation inputs, models and caches behind
   one interface over local files and object storage (GCS, S3, Blob).
6. **Generic reader kinds.** `ocr`, `layout` and `field_extractor` steps bound
   to a provider in the processor catalog, with existing `document_ai_*`
   pipelines migrated; then a second OCR provider to prove the seam.
7. **API address at run time** for the frontend image, or one origin for both
   services, so one image serves every environment.
8. **First deployment**: Cloud Run with a Filestore volume, Secret Manager and
   IAP, from the images CI already builds.

## Collaboration and code health

- **Branch protection on `main`** with CI required, once more than one person
  pushes.
- **Split the largest files by subject**: `app/globals.css` (one stylesheet per
  section), `app/pipelines/pipeline.tsx` and `app/lab/lab.tsx` (their panels as
  components), `backend/app/api/deps.py` (runtime state apart from stores).
  Done so far: the domain models by subject, the frontend components by section.
- **Lifecycle scripts on every OS.** `setup`, `start` and `stop` exist in
  PowerShell only; the npm scripts and the containers already run anywhere.
- **Screenshots in the feature pages**, regenerated from the running app rather
  than drawn, once the UI settles.

## Later

### Branches and parallel execution in the pipeline engine

The visual editor presents the sequential engine as a flowchart; connections
come from step order, so opening and saving an old pipeline preserves its
execution contract. Free connections and parallel branches need an execution
model, explicit input/output contracts and rules for merging results. Keep them
out of the canvas until the engine supports them; a diagram must describe what
will actually run. With branches, methods could propose candidates side by side
rather than in sequence ([0003](docs/decisions/0003-candidates-and-resolution.md)).

### A resolution strategy learned from Lab history

The Lab already scores every method per field and can re-resolve a stored run
under any rule. The rule could be proposed from that history — the method that
was right most often for each field, with the score floor that maximised
accuracy — and shown as a suggestion, never applied on its own.

### TabPFN and Jev, operational

TabPFN is in the algorithm registry and trains once `tabpfn` (with PyTorch) is
installed; decide whether that weight belongs in the default install or in an
optional extra. Jev is listed as not connected: once there is API access, it
joins as a remote step that answers a categorical field from the text without
training here, and is compared like any other method.

### Document types and flows

Today there is one implicit type, invoice, and its entities, prompts, pipeline
and register are global settings. More types makes those per-type, reaching
into settings, storage, Datasets, Lab comparisons, Master Data and most of the
UI. The type is **chosen by the user**, not detected: chosen is most of the
value and is the prerequisite for detection anyway; a categorical field
predicted by a trained model is how detection can arrive later. Postponed until
the new document classes are actually needed. Decide what the runs and datasets
already recorded become before starting.

### Splitting compound PDFs

One PDF may hold several documents, and the app deliberately refuses to merge
page extractions into one incoherent record. A splitting step would emit one
record per document, which is what makes the app usable on a scanned batch
rather than on single files. Expected approach: a custom splitter processor
behind the generic reader kinds above.

### A-priori cost and time estimate

Before a run or an experiment starts, state what it is likely to cost and how
long it will take, from the measured history of that model on that pipeline.
Analytics already computes those per-document figures. With no history for a
combination, say nothing rather than invent a number.

### Further Lab comparison work

- Give historical analysis its own space by moving Run a test into a New
  evaluation action and offering Runs, Analytics, Experiments and Compare as
  peer views.
- Apply field exclusions consistently to thresholds, Runs and Analytics.
  Accuracy thresholds currently use the unadjusted score, and Analytics does
  not expose the exclusion control available in Runs.
- Paired comparison on shared documents for runs compared outside an
  experiment, and label changes between runs shown separately.
- A logarithmic time axis for wide runtime ranges, and missing cost
  measurements explained directly in the chart.
- Per-request context-tier accounting before enabling automatic Gemini 3.1 Pro
  Preview rates. Summed run token counts cannot select a request's tier.

### Resource catalog boundaries

Processors registers existing Google resources; creating, training, deploying
and changing Google's default version remain in Google Cloud. Metadata access is
distinct from process access. Per-step LLM selection and multiple credential
profiles are separate future changes, not implied by a processor catalog.
Document AI pricing remains per type; version-specific pricing would require
matching usage attribution.
