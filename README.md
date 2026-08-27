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
- highlighting of where each extracted value sits on the page, from OCR
  tokens or straight from the Custom Extractor, with zoom;
- extraction by a Google Custom Extractor as an alternative to a language
  model, with the processor's own confidence and the position of each value;
- per-supplier corrections applied after the register identifies the supplier:
  a fixed value, a pattern over what the page said, or one more model call
  about named fields alone;
- comparison of two runs field by field, to see what one change actually
  moved;
- a data-flow note on every run stating where the pages actually go, read from
  the pipeline's steps rather than from which model is selected: a pipeline
  built only from local steps keeps them on the machine, any Document AI step
  uploads them to Google, and a hosted model is named only when the pipeline
  actually calls one.

## Start

Requirements: Python 3.11+, Node.js 22.13.0+, and LM Studio if you want to run
models locally. A vision model is needed only for a pipeline that renders pages;
one that reads OCR text does not need vision.

```powershell
.\setup.ps1
.\start.ps1 -OpenBrowser
```

`setup.ps1` creates the virtual environment, installs the exact Python and Node
dependency versions committed in `backend/requirements.lock.txt` and
`package-lock.json`, and builds the frontend. It is safe to run again — every
step checks before it acts — and it finishes by listing what only a person can
supply.

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

The application configuration is portable, but the inference runtime is still
machine-specific. DocuFlow reads the accelerator from LM Studio and derives its
own safe placement from it, so a laptop with integrated graphics and a
workstation with a discrete card need no copied hardware setting. **LLM** shows
what it found. The LM Studio version, selected runtime backend, drivers and
hardware can still change speed and, occasionally, numerical output; the app
does not claim bit-for-bit equality across unlike inference stacks.

Datasets, pipelines and Master Data do not travel either. Pipelines are recreated
from the built-in default on first run; datasets and register rows are yours to
re-import if you want them on the new machine — copy `backend/data` across to
carry everything, including the run history.


## Where a value came from

The model is never asked for coordinates: asking would multiply output tokens
and invite the same copying failures a small model already makes, and a wrong
rectangle is worse than none because it looks authoritative. Document AI already
returns every token with its box, so the value the model answered is located in
that token stream and the matching boxes are unioned.

The page is shown as an image rather than in the PDF viewer, because nothing
outside that viewer can know where it put the page, so nothing can be laid over
it accurately. Coordinates are normalized, and hold at any size.

An OCR step can be added to a pipeline **purely to supply positions**, without
its text being given to the model — which is how a multimodal model can read
the picture itself and still have its answers highlighted. The choice is on the
step in Pipelines.

Two limits are deliberate. A string that occurs several times in a document is
ambiguous, and the first occurrence is taken. A value the OCR never saw cannot
be highlighted at all, which includes anything the model inferred rather than
read, and anything derived from a register.

## Extraction without a model

A Custom Extractor reads the configured fields itself, so a pipeline built on
it needs no LLM extraction step at all — and nothing in the app waits for a
model such a pipeline will never call. It used to: every run held until the
selected model was loaded and warm, which on a Custom Extractor pipeline cost
minutes and several gigabytes to sit idle while Google did the reading, and on a
machine with no model at all made the pipeline unrunnable. Whether a pipeline
calls a model is now read from its steps, and supplier rules count, because one
of them may be an instruction to ask the model again.

Four more things follow.

**The schema travels with the request.** A generative Custom Extractor accepts a
`schemaOverride` per call, so DocuFlow sends the fields it wants every time
rather than editing the processor's stored schema. Writing Extraction's fields
into the processor whenever someone edited them would make a remote resource
shadow a local one, with two ways to fall out of step and a failed write leaving
them disagreeing silently. This way Extraction stays the one place fields are
defined, and the processor is configured once and left alone.

Each field carries the description written in Extraction, which is what the
processor reads and the difference between a usable answer and a wrong one:
asked for a currency with no description this processor answered `$`, and told
the code was ISO 4217 it answered `USD`. Descriptions need the `v1beta3`
endpoint — `v1` rejects the field outright — so the Custom Extractor alone uses
it, while OCR and the Layout Parser stay on `v1`.

**Each field says how it is to be answered**, and it is the most consequential
line in the schema. `EXTRACT` points at a span on the page, so it can only
return what is printed and cannot be asked for a form the document does not
carry: told a currency must be an ISO 4217 code, an `EXTRACT` field on an
invoice showing only `S$` returned nothing — and a field it cannot satisfy takes
others down with it, which is how the date went missing from the same response.
`DERIVE` lets it work the value out; the same field, the same description, as
`DERIVE`: `SGD`. So dates and currencies are derived and everything else is
extracted, and what a field may be told follows from which it is. A derived
value has no span on the page, so it also has no highlight box.

What a format requires is said in one place, shared by every reader that asks:
Gemini's schema, the Custom Extractor's schema, and a local model's prompt. It
is appended only when the description does not already say it, and that is not
tidiness. A description reading "Normalize it to YYYY-MM-DD" followed by
"Format the value as YYYY-MM-DD" made this processor return **no date at all**,
three times out of three, while either sentence alone worked every time.
Repeating an instruction to a generative reader is not free.

**Confidence comes from the processor**, so nothing asks a model how sure it is.
The number is kept as well as the band the rest of the app reads.

**Boxes come with the entities**, so highlighting needs no separate OCR step and
nothing is searched for in the page text.

What does not change is validation: a currency is a three-letter code whoever
read the page, so a processor answering `$` is corrected exactly as a model
would be.

One thing about this processor is worth knowing before writing a description
for it, and it was measured rather than assumed: it is **generative**, so it
varies. The same document and the same request returned a date on one call and
not the next. What it may be asked for is settled by the method above, not by
how the description is worded.

A field the processor did not answer says so, because silence and an invoice
that genuinely lacks the value look identical otherwise.

## Rules for one supplier

Layouts repeat per supplier, and so do the exceptions: this one prefixes the
number with `Ns. Rif.`, this one always bills in euro, this one writes the date
the other way round. A general prompt cannot absorb all of that without getting
worse at everything else, so the corrections live beside the supplier in Master
Data and run in a `Supplier rules` step placed after the register lookup.

They key on `id_subject`, never the supplier's name: several spellings of one
supplier legitimately resolve to the same internal id, and the id is the thing
that is either right or wrong. A document whose supplier was not identified gets
no rules at all — inheriting somebody else's corrections is worse than applying
none.

Two kinds, deliberately separated. A fixed value or a pattern costs nothing,
cannot hallucinate, and is what most supplier exceptions actually are. A
prompted rule is one more model call, and separating them is what makes that
call happen only when there is something to ask — and then about the named
fields alone, so the rest of the extraction is left as it was.

Whether the layer earns its cost is measurable the same way everything else is:
a pipeline with the step and one without are two runs, and Lab compares them
field by field.

## Working on it

Conventions, the commands that check a change, and the traps that have already
cost time are in [AGENTS.md](AGENTS.md) — written for whoever picks this up on
another machine, human or agent.

```powershell
.\stop.ps1      # stop the frontend and backend
.\restart.ps1   # rebuild the frontend and restart both
```

`npm test` is the type check, the linter, the frontend tests and the backend
tests. It does not build, so it is safe to run against a live app. `npm run
verify` adds the build, and a build landing under a running server leaves it
stale.

That staleness is worth recognising, because it does not look like a fault:
`vinext start` reads its manifest once and serves client chunks by content hash,
so after a rebuild the page still answers 200 while the scripts it names are
gone. React never boots, the sidebar renders, and every click does nothing.
`start.ps1` and `restart.ps1` detect it — they ask for each chunk the page names,
not just the page — and rebuild.

The lifecycle scripts identify a running service by both its listener port and
its process command line. If another project owns port 3000 or 8000, startup
stops with that PID in the error; it never adopts or terminates the foreign
process.

## Architecture

```text
React frontend
    ↓
FastAPI
    ↓
DocumentPipeline — the steps the chosen pipeline names, in order
    │
    ├── render pages ............ the first pages allowed, as images
    ├── Document AI OCR ......... text and token boxes, from Google
    ├── Document AI Layout ...... structured text, from Google
    ├── Document AI Custom
    │     Extractor ............. the fields themselves, from Google
    ├── LLM extraction .......... the fields themselves, from a model
    ├── regex refinement ........ per-field patterns over the result
    ├── master data lookup ...... an internal id from the register
    └── supplier rules .......... the corrections written for one supplier
                    ↓
             JSON Schema + Pydantic
```

`DocumentPipeline` runs independent steps, each declaring what it needs and what
it leaves behind, so a pipeline can be checked while it is being written. Not
every step is present in every pipeline, and two of them are alternatives: a
pipeline extracts with a model **or** with the Custom Extractor. Future steps —
document classification, splitting compound PDFs, validation with a second model
— are a contract and a compiler case, not a UI change.

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

The UI reports load, warm-up and document-processing times separately. Extraction is rejected until the active model is loaded, so LM Studio cannot silently auto-load it inside the document timer — for a pipeline that calls a model at all. One that does not is never held back by a model it will not use, and says so where the model is named.

Every new Workspace and Lab run also records the execution profile that was
actually selected: provider profile, model parameters, quantization, file size,
context, concurrency, deterministic seed and, for hosted models, thinking
level. Lab shows the profile on the run and includes it in both CSV exports. A
model id by itself is not enough evidence that two runs used the same artefact
and controls. The full pipeline definition is stored with each new Lab run as
well; editing or deleting a pipeline later does not rewrite that history. A
retry is refused when the active provider/model profile differs from the
recorded one instead of combining two configurations into one accuracy figure.
A pipeline with no model step records `Not used` rather than the unrelated model
currently selected in LLM. Older runs retain `null` for facts the previous
database schema did not record.

This provenance makes cross-PC differences explainable, not impossible. For a
strict comparison use the same GGUF quantization, LM Studio and runtime-backend
versions, driver family and pipeline snapshot; then compare the stored profile
and CSV columns before attributing a score change to prompt quality.

The snapshot currently freezes the pipeline definition and model controls, not
the deployed revision of a remote Document AI processor or the contents of
Master Data and supplier rules. A retry after one of those mutable inputs has
changed can therefore produce a different answer even when the stored pipeline
and model profile match; use a new run when comparing such a change.

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

If a model returns a value in the wrong format, only that field is cleared and marked for review. Other valid entities remain available. A currency is stored as a three-letter ISO 4217 code, with whitespace removed and lowercase canonicalized. A symbol naming exactly one currency is read as that currency — `S$` is Singapore's and nobody else's — while a bare `$` belongs to a dozen countries and is refused, because a wrong currency on an invoice is worse than an empty one. That line used to sit at every symbol, which was right while only models read the page: a model writing `$` had chosen not to give the code. A processor that points at a span can only answer with what is printed, and documents print symbols.

## Why Outlines is not required

LM Studio directly supports `response_format.type = json_schema`. The backend supplies the dynamic schema in every `/v1/chat/completions` extraction request, so the Structured Output field in the LM Studio desktop UI does not need to be configured manually. Pydantic provides a second application-level validation layer. Outlines remains a useful future adapter for direct Transformers or MLX inference, but would duplicate the structured-output layer in this setup.

References: [LM Studio Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [LM Studio model loading API](https://lmstudio.ai/docs/developer/rest/load), [Outlines multimodal models](https://dottxt-ai.github.io/outlines/main/features/models/transformers_multimodal/).
