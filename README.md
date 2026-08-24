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
- composable pipelines: page rendering, Document AI OCR and Layout Parser, the model call, per-field regex rules and master-data lookup, with a per-pipeline page limit;
- editable system, extraction and confidence prompts;
- configurable entities with name, format and description, each either read from the document or derived by a pipeline step;
- qualitative `low`, `medium` or `high` confidence for every value;
- field-tolerant validation: one invalid value is set to `null/low` without discarding valid fields;
- editable review fields, including missing values, with undo and manual-edit tracking in the JSON export;
- initial schema with `date`, `document_number`, `supplier_name`, `currency` and `total_amount`;
- JSON constrained by JSON Schema and validated with Pydantic;
- JSON export;
- no document data sent to external services.

## Start

Requirements: Python 3.11+, Node.js 22+ and LM Studio with at least one model installed. A vision model is needed only for a pipeline that renders pages; one that reads OCR text does not need vision.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm install
.\start.ps1 -OpenBrowser
```

`npm run start` serves a production build and never creates one, so `start.ps1`
runs `npm run build` itself when `dist/` is missing.

After changing any frontend code, restart with a rebuild in one step:

```powershell
.
estart.ps1
```

Building under a running server is what breaks the app silently: `vinext start`
loads `dist/server/index.js` once and serves client chunks by content hash, so a
rebuild leaves it pointing at hashes that no longer exist. The page still renders,
but React never hydrates and every click does nothing.

`npm test` no longer builds, so it is safe to run against a live app: it is the
type check, the frontend tests and the backend tests. `npm run verify` adds the
build, and leaves a running frontend stale — re-run `.\restart.ps1` after it.

`start.ps1` and `restart.ps1` detect the stale state on their own too. They ask
for every chunk the served page names, not just the page, because this failure
answers 200 on the page itself.

To stop the frontend and backend:

```powershell
.\stop.ps1
```

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

The LLM section's flow is `select → Load & warm up → process`. DocuFlow unloads other models before loading the selected one, uses an 8,192-token context and runs a minimal warm-up — with an image only when the selected pipeline actually sends images, since some models answer text and kill the runtime on any image.

A model is kept off the integrated GPU when any of three signals says it will not fit: an IQ quantization, a file of at least 8 GB, or at least 20 billion parameters. That last one is not redundant: `bonsai-27b` is 27B in a 4.4 GB Q1_0 file, and the runtime allocates for the parameter count, not the file size. Those models are loaded through the LM Studio CLI with GPU-layer offload disabled and one parallel request. The incompatible `Qwen3.8 27B UD` variant is excluded locally.

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
