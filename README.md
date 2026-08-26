# DocuFlow — local document agent

POC for extracting structured data from invoice PDFs, through composable pipelines: page rendering or Google Document AI, a local model in LM Studio or the Gemini API, then deterministic steps over the result.

## Included features

- PDF upload up to 20 MB;
- side-by-side PDF preview of the uploaded document during review;
- one vision-model call containing the first pages allowed by the configured page maximum;
- explicit cut notice showing processed pages and total pages;
- persistent model and pipeline selection;
- automatic discovery and periodic refresh of installed models, vision or text-only;
- explicit single-model `Load & warm up` phase with separate load and warm-up timing;
- a reproducible local-model profile (8,192 context, one parallel request,
  fixed evaluation settings and seed) rather than LM Studio UI defaults that
  vary from one PC to another;
- immediate cancellation of a Workspace extraction or Lab run, including the
  document currently waiting on the model;
- composable pipelines: page rendering, Document AI OCR and Layout Parser, the model call, per-field regex rules and master-data lookup, with a per-pipeline page limit;
- editable system, extraction and confidence prompts;
- configurable entities with name, format and description, each either read from the document or derived by a pipeline step;
- qualitative `low`, `medium` or `high` confidence for every value;
- field-tolerant validation: one invalid value is set to `null/low` without discarding valid fields;
- editable review fields, including missing values, with undo and manual-edit tracking in the JSON export;
- initial schema with `date`, `document_number`, `supplier_name`, `currency` and `total_amount`;
- JSON constrained by JSON Schema and validated with Pydantic;
- JSON export;
- a data-flow note on every run stating where the pages actually go: a
  pipeline built only from local steps keeps them on the machine, one with a
  Document AI step uploads them to Google, and a hosted model sends them to
  its API.

## Start

Requirements: Python 3.11+, Node.js 22+, and LM Studio if you want to run models
locally. A vision model is needed only for a pipeline that renders pages; one
that reads OCR text does not need vision.

```powershell
.\setup.ps1
.\start.ps1 -OpenBrowser
```

`setup.ps1` creates the virtual environment, installs both dependency sets and
builds the frontend. It is safe to run again — every step checks before it acts —
and it finishes by listing what only a person can supply.

### On a machine DocuFlow has not run on before

Nothing under `backend/data` is in the repository: it holds API keys, run history
and real invoices. A fresh clone therefore starts empty, and three things are
yours to provide.

**A model.** No model is selected by default, because which models exist depends
on the machine. Open **LLM**, pick one from the list LM Studio reports, and use
`Load & warm up`.

**A Gemini key**, only for the hosted models. Paste it under **LLM**. It is stored
in `backend/data/settings.json` on that machine and is never sent back to the
browser.

**A Document AI service account**, only for the OCR and Layout Parser pipelines.
Save the JSON key as `backend/data/gcp-service-account.json`, then fill in the
project id, region and processor ids under **Settings**.

Nothing else is machine-specific. How models are loaded adapts on its own: the
app reads the accelerator from LM Studio and derives its own limits from it, so a
laptop with integrated graphics and a workstation with a discrete card each get
the right decision without a setting to change. **LLM** shows what it found.

Datasets, pipelines and Master Data do not travel either. Pipelines are recreated
from the built-in default on first run; datasets and register rows are yours to
re-import if you want them on the new machine — copy `backend/data` across to
carry everything, including the run history.


## Working on it

```powershell
.\stop.ps1      # stop the frontend and backend
.\restart.ps1   # rebuild the frontend and restart both
```

`npm test` is the type check, the frontend tests and the backend tests. It does
not build, so it is safe to run against a live app. `npm run verify` adds the
build, and a build landing under a running server leaves it stale.

That staleness is worth recognising, because it does not look like a fault:
`vinext start` reads its manifest once and serves client chunks by content hash,
so after a rebuild the page still answers 200 while the scripts it names are
gone. React never boots, the sidebar renders, and every click does nothing.
`start.ps1` and `restart.ps1` detect it — they ask for each chunk the page names,
not just the page — and rebuild.

## Architecture

```text
React frontend
    ↓
FastAPI
    ↓
DocumentPipeline
    ├── InspectPdf
    │       └── apply the configured page maximum
    └── ExtractConfiguredEntities
            ├── render those pages as images
            └── send every image in one vision call
                    ↓
                LM Studio
                    ↓
             JSON Schema + Pydantic
```

`DocumentPipeline` runs independent steps, each declaring what it needs and what it leaves behind, so a pipeline can be checked while it is being written. Today's steps: render pages, Document AI OCR, Document AI Layout Parser, the model call, master-data lookup and regex refinement. Future steps — document classification, splitting compound PDFs, validation with a second model — are a contract and a compiler case, not a UI change.

## Model lifecycle and timing

The LLM section's flow is `select → Load & warm up → process`. DocuFlow unloads other models before loading the selected one and applies its own standard profile: an 8,192-token context, one parallel request, batch size 512, Flash Attention enabled, KV cache in system memory and a fixed inference seed. Those values are sent explicitly even for small models; otherwise LM Studio inherits preferences from its UI and the same GGUF can behave differently on two PCs. The warm-up is minimal, with an image only when the selected pipeline actually sends images, since some models answer text and kill the runtime on any image.

Every free-text value in the schema carries a length ceiling. The schema becomes a grammar, and a grammar that permits an unbounded string permits one forever: a model too small for the document cannot answer with invalid JSON, so it stays inside an open value and repeats until the token budget or the request timeout ends it. Bounded, the same model fails one field in seconds and the run carries on — which is what makes the app's behaviour a property of the app rather than of whichever model the host happens to have.

Whether a model's layers are offloaded to the accelerator is still decided from the machine: forcing the same GPU placement on unlike hardware would make the profile consistently fail rather than consistently behave. `lms runtime survey` reports the accelerator available to the runtime LM Studio currently has selected; an integrated adapter is budgeted well below the figure it advertises, because that figure is a slice of system RAM a single allocation cannot rely on. What a model needs is the larger of its file and what its parameter count implies — `bonsai-27b` is 27B in a 4.4 GB Q1_0 file, and the runtime allocates for the parameters, not the file. When the second exceeds the first, the model is loaded through the LM Studio CLI with offload disabled while retaining the common context and concurrency envelope. A runtime that explicitly reports no accelerator uses the standard REST profile: it is already processor-only, while the REST endpoint can apply settings the CLI does not expose. An unreadable host remains the conservative case.

LM Studio model keys are not stable across all releases: the same installation
may be reported as `qwen3.5-0.8b` or
`lmstudio-community/qwen3.5-0.8b`. DocuFlow migrates such a key only when its
basename identifies exactly one installed model. Ambiguous matches are left for
the user to choose.

Cancel is cooperative at the pipeline boundary and immediate at awaited provider
calls. The backend cancels the task in flight, which closes the HTTP request to
LM Studio, Gemini or Document AI, and does not execute later steps. A short
synchronous operation already running inside a local step may finish before the
task reaches its next cancellation point; its result is discarded.

The LLM section reports the accelerator found and the budget derived from it, which is how you check what the app concluded about a machine it has never run on. A machine it cannot read loads conservatively: offloading blind is what ends a run mid-way.

Note that `--gpu off` governs the model's own layers. A vision projector follows the selected runtime, so on a GPU build page images are encoded on the GPU whatever the load flags said.

The UI reports load, warm-up and document-processing times separately. Extraction is rejected until the active model is loaded, so LM Studio cannot silently auto-load it inside the document timer.

## Multi-page documents

The app deliberately does not extract page blocks and merge their values. A large PDF may contain multiple invoices or document types, so merging independent extractions could create an incoherent record.

Instead, it sends the number of initial pages the pipeline allows together in one model call. The parameter count and theoretical context length are not used to choose a page limit. If the selected maximum exceeds the context actually available to the loaded model, LM Studio rejects the request and its context must be changed when loading the model.

The UI reports `pages 1–N of M`. If `N < M`, the remaining pages were not sent to the model. The complete original PDF remains available in the preview for human review.

Rendered pages are held in memory as base64 until the model answers, so a single
request is capped at a 64 MB image budget. Exceeding it fails with an explicit
message instead of exhausting the backend process.

## Confidence

Confidence is a qualitative model assessment, not a calibrated probability. Its rubric is editable in Extraction. By default:

- `high`: clearly visible, explicitly labelled and unambiguous;
- `medium`: readable but identified through context or with minor ambiguity;
- `low`: partial, conflicting, hard to read or unavailable.

The backend always normalizes a `null` value to `low` confidence.

If the model runs out of output tokens before closing the JSON object, the request
fails with an explicit output-limit message rather than a generic parse error: a
retry would only add prompt tokens and could never recover.

If a model returns a value in the wrong format, only that field is cleared and marked for review. Other valid entities remain available. Currency symbols are deliberately not inferred: only three-letter ISO 4217 codes are accepted, with whitespace removed and lowercase letters canonicalized to uppercase.

## Why Outlines is not required

LM Studio directly supports `response_format.type = json_schema`. The backend supplies the dynamic schema in every `/v1/chat/completions` extraction request, so the Structured Output field in the LM Studio desktop UI does not need to be configured manually. Pydantic provides a second application-level validation layer. Outlines remains a useful future adapter for direct Transformers or MLX inference, but would duplicate the structured-output layer in this setup.

References: [LM Studio Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [LM Studio model loading API](https://lmstudio.ai/docs/developer/rest/load), [Outlines multimodal models](https://dottxt-ai.github.io/outlines/main/features/models/transformers_multimodal/).
