# Development

Setting DocuFlow up, running it, checking a change, and the traps that have
already cost time. Conventions for writing code and documentation are in
[CONTRIBUTING](../CONTRIBUTING.md).

## Requirements

Python 3.13 (3.11+ works), Node.js 22.13.0+, and LM Studio to run models
locally. A vision model is needed only for a pipeline that renders pages; one
that reads text does not need vision. Docker is optional, for the containers.

## Setting up and running

On Windows, the lifecycle scripts do everything:

```powershell
.\setup.ps1                 # once per machine: venv, dependencies, first build
.\start.ps1 -OpenBrowser    # backend on :8000, frontend on :3000
.\stop.ps1                  # stop both
.\restart.ps1               # rebuild the frontend and restart both
```

`setup.ps1` creates the virtual environment, installs the exact Python and Node
dependency versions committed in `backend/requirements.lock.txt` and
`package-lock.json`, and builds the frontend. It is safe to run again — every
step checks before it acts — and it finishes by listing what only a person can
supply.

On macOS or Linux, the same steps by hand:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --requirement backend/requirements.lock.txt
npm ci
npm run build
(cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000) &
npm run start
```

Or in containers, on any OS: `docker compose up --build` ([deployment](deployment.md)).

The lifecycle scripts identify a running service by both its listener port and
its process command line. If another project owns port 3000 or 8000, startup
stops with that PID in the error; it never adopts or terminates the foreign
process.

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

**A Document AI service account**, for OCR, Layout Parser and Custom Extractor
steps. Save the JSON key as `backend/data/gcp-service-account.json` (or point
`DOCUFLOW_GCP_CREDENTIALS` at it), then fill in the project and region defaults
under **Processors → Connection and pricing**. Register each processor in
**Processors**, then choose it and its version in the relevant pipeline step.

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

## Checking a change

```bash
npm test          # type check, lint, frontend tests, backend tests
npm run verify    # the above, then the production build
```

`npm test` does not build, so it is safe to run while the app is up. The npm
scripts reach the virtualenv through `scripts/python.mjs`, which finds its
interpreter on Windows and elsewhere. CI (`.github/workflows/ci.yml`) runs the
build and `npm test` on Windows, the backend tests again against PostgreSQL,
and builds and starts the container images on Linux, for every push to `main`
or `cloud` and every pull request.

To run the backend tests against PostgreSQL yourself, point
`DOCUFLOW_TEST_DATABASE_URL` at a database you can create schemas in; each test
gets one of its own and drops it after (`backend/tests/conftest.py`).

**A build landing under a running `vinext start` leaves it stale**, and the
failure does not look like one: `vinext start` reads its manifest once and
serves client chunks by content hash, so after a rebuild the page still answers
200 while the scripts it names are gone. React never boots, the sidebar renders,
and every click does nothing. `start.ps1` and `restart.ps1` detect it — they
request each chunk the page names, not just the page — so run one of them after
building.

## Generated and locked files

**`lib/types.ts` is generated** from the FastAPI OpenAPI schema. Change the
Pydantic models in `backend/app/domain/`, then run `npm run types:generate`.
`test_generated_types.py` fails whenever the committed file and the live schema
disagree. Never edit it by hand.

**Dependency locks are part of the cross-machine behaviour.** `setup.ps1`, CI
and the images install `backend/requirements.lock.txt` and run `npm ci`;
changing only a range in `backend/requirements.txt` changes no fresh install.
Update the environment from the direct requirements, run the full suite, then
regenerate and commit the lock deliberately. `package-lock.json` receives the
same treatment: change it through npm and never replace `npm ci` with
`npm install` in setup.

## Interface conventions

Help buttons open on hover, keyboard focus or tap. Escape or an outside click
closes them. Help is rendered outside scrolling cards and kept inside the
viewport. Descriptions refer to the extraction engine when both LLMs and Custom
Extractors are supported. Pareto explanations follow the selected resource axis;
missing resource measurements are disclosed rather than silently treated as
zero. The interface is in English.

## Known traps

**`backend/data` is not in the repository.** A fresh clone has no settings,
selected model, credentials or history and must still start.
`backend/tests/test_fresh_install.py` is where that is nailed down.

**Prefer a map typed by a generated union over a map keyed by `string`.**
`STEP_LABELS` was `Record<string, string>`, went two step kinds without an
entry, and Lab showed runs as `document_ai_extract → supplier_rules`. Typed
`Record<StepKind, string>`, the same omission would not compile.

**LM Studio is per machine and may not be there at all.** The `lms` CLI may be
missing, the server may not be running, and the same installed model can be
reported as `qwen3.5-0.8b` or `lmstudio-community/qwen3.5-0.8b`. Hardware is
read at runtime and the loading profile is derived from it; nothing about the
accelerator is assumed.

**A run's model id is not its execution configuration.** New runs snapshot the
provider controls and local-model artefact metadata (parameters, quantization
and file size); Lab evaluations snapshot the complete pipeline definition. Keep
those fields when adding stores or exports. A retry must not merge a new profile
into an old evaluation; historical rows from before the columns existed say
`null` rather than inventing the missing facts. A pipeline that cannot call a
model records provider `none` and model `Not used`, not the selection sitting in
settings. LM Studio/runtime/driver versions are not exposed reliably, so do not
promise bit-identical output across different inference stacks.

**Lab snapshots are what make a retry the same experiment.** New evaluations
resolve and pin each processor version when metadata is available, store a
fingerprint and a snapshot of the supplier register and rules, and freeze their
input PDFs and labels in `backend/data/evaluation-inputs`. Retry and historical
preview read that snapshot, never the current dataset. Legacy runs without a
manifest cannot be retried; keep that distinction when changing the API or UI.
Usage completeness is separate from a successful extraction: do not turn
missing billable counters into a zero or a complete cost estimate.

**Ports do not establish process ownership.** `start.ps1` and `stop.ps1` use
`scripts/process-safety.ps1` before adopting or stopping a listener. Keep
`backend/tests/test_powershell_scripts.py` green when changing the lifecycle
scripts.

**Document AI: `v1` for OCR and the Layout Parser, `v1beta3` for the Custom
Extractor.** Only `v1beta3` accepts a `description` on a schema property, and
`v1` rejects the field outright. Every `:process` response is wrapped —
`{"document": {…}}` — and forgetting to unwrap it looks exactly like a
processor that returned nothing.

**A schema property's `method` decides what it may be asked for.** `EXTRACT`
points at a span on the page and can only answer with what is printed; `DERIVE`
lets the processor work the value out. Telling an `EXTRACT` field to produce a
form the page does not carry makes it return nothing *and* costs the other
fields in the same response.

**Repeating an instruction to a generative reader is not free.** A description
reading "Normalize it to YYYY-MM-DD" followed by "Format the value as
YYYY-MM-DD" made the processor return no date at all, three times out of three,
while either sentence alone worked every time.

**A trimmed PDF is not byte-stable.** PyMuPDF writes a fresh document id into
every copy, so the same page cut made twice never hashes the same; the reading
cache keys on the original PDF and the page count instead.
