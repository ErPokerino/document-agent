# Language models and Document AI processors

The local and hosted models extraction can run on, how a local model is loaded, and the catalog of Document AI processors.

## Processors and models

**Processors** is the local catalog of existing Google Document AI resources,
with All, OCR, Layout Parser and Custom Extractor views and a search field.
Each entry has its own project and region; credentials are shared through the
local service-account file. Registration does not create or deploy a Google
resource. Metadata checks list versions without processing a document and do
not establish permission to process documents. Names can change; resource
identities cannot. A processor used by a saved pipeline cannot be removed.

**Pipelines** selects a compatible processor and either an explicit version or
the processor's Google Cloud default for each Document AI step. New steps require
a choice. Existing defaults and step overrides are migrated into the catalog
without changing the target or version. Original settings and pipeline files
are retained as `.pre-processors.bak` files inside ignored `backend/data`.

New Lab runs save concrete project, region and processor bindings independently
of the catalog and pin resolved versions when metadata is available. OCR and
Layout versions are included in Analytics grouping, alongside extractor identity.
Missing historical bindings remain unknown. A default whose version cannot be
resolved remains mutable; use explicit versions for controlled comparisons.

**LLM** separates Local and API resources. The location tabs replace the former
Runs filter; capability filters remain, and disk-size filtering applies only to
Local. Switching tabs does not change the selected model, and the selection
remains visible. The active LLM is still shared by model-calling pipeline steps.
The API tab holds a rate per million tokens for each hosted model, used to
estimate the cost of runs. Rates can be edited, removed, and added for any
hosted model that has none. A new installation starts with a rate for each
selectable model; a default is offered once, so a removed rate stays removed.
A retired model keeps its rate only where an installation already had one,
marked *retired*, for the cost of its old runs.
**Settings** contains app appearance; Document AI connection and pricing live
with the processors that use them.

## Model lifecycle and timing

The LLM section's flow is `select → Load & warm up → process`. DocuFlow unloads other models before loading the selected one and applies its own standard profile: an 8,192-token context, one parallel request, batch size 512, Flash Attention enabled, KV cache in system memory and a fixed inference seed. Those values are sent explicitly even for small models; otherwise LM Studio inherits preferences from its UI and the same GGUF can behave differently on two PCs. The warm-up is minimal, with an image only when the selected pipeline actually sends images, since some models answer text and kill the runtime on any image.

Every free-text value in the schema carries a length ceiling. The schema becomes a grammar, and a grammar that permits an unbounded string permits one forever: a model too small for the document cannot answer with invalid JSON, so it stays inside an open value and repeats until the token budget or the request timeout ends it. Bounded, the same model fails one field in seconds and the run carries on — which is what makes the app's behaviour a property of the app rather than of whichever model the host happens to have.

Whether a model's layers are offloaded to the accelerator is still decided from the machine: forcing the same GPU placement on unlike hardware would make the profile consistently fail rather than consistently behave. `lms runtime survey` reports the accelerator available to the runtime LM Studio currently has selected; an integrated adapter is budgeted well below the figure it advertises, because that figure is a slice of system RAM a single allocation cannot rely on. What a model needs is the larger of its file and what its parameter count implies — `bonsai-27b` is 27B in a 4.4 GB Q1_0 file, and the runtime allocates for the parameters, not the file. When the second exceeds the first, the model is loaded through the LM Studio CLI with offload disabled while retaining the common context and concurrency envelope. A runtime that explicitly reports no accelerator uses the standard REST profile: it is already processor-only, while the REST endpoint can apply settings the CLI does not expose. An unreadable host remains the conservative case.

Qwen 3.5 is also kept on the processor when the host exposes integrated adapters only. This was measured with the 0.8B Q8 model on Intel UHD driver `32.0.101.7085`: Vulkan runtimes 2.28.2 and 2.29.1 both emitted repeated multilingual tokens for even an `OK` prompt, with or without Flash Attention, while the same GGUF answered correctly with `--gpu off`. LM Studio's model API does not report GPU-layer placement, so a CPU-safe model found loaded after a backend restart is reloaded explicitly rather than trusted from matching context and parallelism alone. Text pipelines also run the small `OK` probe before their schema warm-up; a grammar-valid response by itself cannot reveal corrupted token generation.

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

New Lab snapshots freeze the pipeline definition, model controls, PDF inputs,
labels, the supplier register and the supplier rules. A fingerprint of that
configuration is stored with the run. Custom Extractor revisions are also
pinned when processor metadata is available. Other remote processors remain
whatever Google serves. A run recorded before the register snapshot uses today's
tables on retry, and the Lab says so.

## A model server

A deployment can serve open models from its own server instead of LM Studio:
llama.cpp, vLLM, Ollama or anything else that speaks the OpenAI-compatible
API. With `DOCUFLOW_MODEL_SERVER_URL` set, the models it lists appear in LLM
beside the others, tagged *Model server*, with what the server reports about
each — llama.cpp gives parameters, quantization, size, context, parallel slots
and whether the model reads images; a server that gives only ids leaves them
blank and the capabilities unknown. They are chosen the same way. They
need no loading here — the server holds the model it was started with — and
answer the same request LM Studio is sent: the same prompt, the same schema
constraint, temperature 0 and a fixed seed, at `/v1/chat/completions`. A run
records the provider `model_server`, what the request fixes, and what the
server reported about the model it ran on. Where a deployment runs no LM Studio
(`DOCUFLOW_LM_STUDIO=off`), the *Local* tab becomes *Self-hosted* and shows the
model server in place of the LM Studio connection.

On Google Cloud this is llama.cpp on Cloud Run, private and called with the
app's identity (`DOCUFLOW_MODEL_SERVER_AUTH=google_id_token`); see
[deployment](../deployment.md#google-cloud). It scales to zero, so the first
request after a pause waits for the model to load.

## Why Outlines is not required

LM Studio directly supports `response_format.type = json_schema`. The backend supplies the dynamic schema in every `/v1/chat/completions` extraction request, so the Structured Output field in the LM Studio desktop UI does not need to be configured manually. Pydantic provides a second application-level validation layer. Outlines remains a useful future adapter for direct Transformers or MLX inference, but would duplicate the structured-output layer in this setup.

References: [LM Studio Structured Output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [LM Studio model loading API](https://lmstudio.ai/docs/developer/rest/load), [Outlines multimodal models](https://dottxt-ai.github.io/outlines/main/features/models/transformers_multimodal/).
