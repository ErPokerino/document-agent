# Architecture

DocuFlow is a FastAPI backend and a React frontend. The backend owns every
decision and every byte of state; the frontend draws what the API returns and
holds nothing a reload would lose. Both run on one machine, and as containers
anywhere — on Google Cloud from the `cloud` branch ([deployment](deployment.md)).

```text
Browser ── React app (vinext) ── HTTP/JSON ──► FastAPI
                                                 │
            ┌────────────────────────────────────┼─────────────────────────────┐
            │                                    │                             │
      Pipeline engine                     Lab & experiments             Models (training)
   steps → candidates → value      runs, snapshots, fingerprints     algorithms, artefacts
            │                                    │      └──── long work as jobs ─────┤
            │                                    │      in process, or a worker elsewhere
            └──────────── adapters to external services and storage ───────────┘
   LM Studio · model server · Gemini · Document AI · SQLite or PostgreSQL · files under DOCUFLOW_DATA_DIR
```

## The pipeline engine

A **pipeline** is an ordered list of steps. Each step declares what it needs and
what it leaves behind (`backend/app/pipeline/definition.py`), so the compiler
refuses a pipeline whose steps cannot be satisfied in order — while it is being
composed, not on the third document of a run.

```text
DocumentPipeline — the steps the chosen pipeline names, in order
    │
    ├── render pages ............ the first pages allowed, as images
    ├── read PDF text ........... the text a native PDF carries, on this machine
    ├── Document AI OCR ......... text and token boxes, from Google
    ├── Document AI Layout ...... structured text, from Google
    ├── Document AI Custom
    │     Extractor ............. the fields themselves, from Google
    ├── LLM extraction .......... the fields themselves, from a model
    ├── trained model ........... fields predicted by a model trained in Models
    ├── regex refinement ........ per-field patterns over the result
    ├── master data lookup ...... an internal id from the register
    ├── supplier rules .......... the corrections written for one supplier
    └── resolve candidates ...... the value chosen among what the steps proposed
                    ↓
             JSON Schema + Pydantic
```

Every step that writes a field leaves a **candidate**; without a Resolve step
the last one is the value ([pipelines](features/pipelines.md)). Whether a
pipeline calls a model, and whether pages leave the machine, are read from its
steps — never assumed from the selected model.

## Reproducibility

A Lab run records what it ran with so it can be compared and retried later:
the input PDFs by hash, the labels, the prompts, the full pipeline definition,
the model execution profile, pinned processor versions, the supplier register
and rules. A fingerprint of all of it groups runs of the same configuration.
Details in [Lab](features/lab.md).

## Long work

A Lab run, an experiment, a training run and a fine-tuning export are recorded
as a **job** (`backend/app/jobs/`): the endpoint checks the request, records
the run and its job, and returns. The work runs in the API process, or — when
deployed — in a worker container started for that job, which rebuilds
everything from the recorded rows. Progress and Cancel go through the job's
row, so both work across machines
([0007](decisions/0007-long-work-as-recorded-jobs.md)).

## Code map

```text
app/                       React, one folder per section of the UI
  page.tsx                 the shell: navigation and every section's host
  components/              pieces shared between sections
  workspace/ extraction/ pipelines/ master-data/ datasets/ lab/ models/
  llm/ processors/ settings/
lib/                       frontend logic worth testing on its own
  types.ts                 generated from the API schema — never edited by hand
tests/                     Node tests, one file per lib module

backend/app/
  main.py                  the FastAPI app, sign-in check; one router per subject
  config.py                where state lives and who may call: DOCUFLOW_* variables
  worker.py                runs one recorded job and exits: the deployed worker's entry point
  jobs/                    the job table, its runners (in process, Cloud Run), the dispatcher
  api/deps.py              stores and helpers every router shares
  api/routes/              endpoints, one module per section
  domain/                  Pydantic models, one module per subject; models.py re-exports them
  pipeline/                step contracts, the compiler, the engine, the steps, resolution
  services/                adapters: LM Studio, model server, Gemini, Document AI, runtime
                           identity, master data, caches, the database (SQLite or PostgreSQL)
  evaluation/              datasets, scoring, classification, Lab store, experiments
  training/                features, algorithms, classifiers, KNN, artefact registry
backend/tests/             pytest, one file per concern

deploy/                    container images; compose.yaml at the root runs them
  gcp/                     Google Cloud: provisioning, Cloud Build, Cloud Run, data migration
scripts/                   lifecycle helpers shared by the PowerShell scripts and npm
docs/                      this documentation
```

## Where vendor-specific code lives

Each external service is reached through one module, so replacing or adding a
provider touches that module and its registration, not the callers.

| Concern | Interface | Implementations today |
|---|---|---|
| Field extraction by a language model | `ExtractionProvider` (`services/extraction_provider.py`) | `LMStudioClient`, `ModelServerClient` (any OpenAI-compatible server), `GeminiClient` |
| Reading pages (OCR, layout, custom extraction) | pipeline steps over `DocumentAiClient` (`services/document_ai.py`) | Google Document AI |
| Trained models | `Algorithm` registry (`training/algorithms.py`) | scikit-learn, LightGBM, XGBoost, CatBoost; TabPFN and Jev listed |
| Relational state | `services/db.py`; stores write SQLite's dialect, translated there | SQLite file, or PostgreSQL by `DOCUFLOW_DATABASE_URL` |
| Long work | job runners (`jobs/queue.py`) | in process, Cloud Run jobs |
| Google credentials | key file, or `services/gcp_runtime.py` | service-account key, or the platform's identity |
| Files: datasets, models, caches, inputs | stores rooted at `config.data_dir()` | local filesystem, or a mounted volume or bucket |
| Configuration and secrets | `config.py`, `settings.json` | environment variables and the data folder |

What it would take to swap each one is in [deployment](deployment.md#what-is-not-portable-yet).
