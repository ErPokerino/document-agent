# Working on DocuFlow

For whoever picks this up next, human or agent, on a machine that is not the one
it was written on.

DocuFlow extracts structured fields from invoice PDFs. A **pipeline** is an
ordered list of steps; a step declares what it needs and what it leaves behind,
and the compiler refuses a pipeline whose steps cannot be satisfied in order.
Extraction happens either in a language model (local through LM Studio, or the
Gemini API) or in a Google Document AI Custom Extractor. Everything else —
regex refinement, the register lookup, per-supplier rules — runs over the
result.

`README.md` explains what is built and why. `ROADMAP.md` holds what was decided
against for now, with the reasoning. Both are meant to outlive the conversations
that produced them: **when you make a decision worth keeping, write it there**,
not only in a commit message.

## Running it

```powershell
.\setup.ps1                 # once per machine: venv, dependencies, first build
.\start.ps1 -OpenBrowser    # backend on :8000, frontend on :3000
.\stop.ps1                  # stop both
.\restart.ps1               # rebuild the frontend and restart both
```

Windows and PowerShell throughout. `npm run test:backend` invokes
`.venv\Scripts\python.exe` directly, so the scripts are not portable to POSIX as
written.

## Checking your work

```bash
npm test
```

Type check, linter, 200-plus frontend tests, 700-plus backend tests. It does not
build, so it is safe to run while the app is up.

```bash
npm run verify
```

The above plus the production build. **A build landing under a running
`vinext start` leaves it stale**, and the failure does not look like one: the
page still answers 200 while the client chunks it names are gone, so React never
boots, the shell renders, and every click does nothing. `start.ps1` and
`restart.ps1` detect it — they request each chunk the page names, not just the
page — so run one of them after building.

## Things that will cost you a day

**`backend/data` is not in the repository.** Settings, API keys, the run
database, datasets and real invoices all live there. A fresh clone has none of
it and must still start, so never assume a settings file, a selected model,
credentials or history exist. `backend/tests/test_fresh_install.py` is where
that is nailed down.

**`lib/types.ts` is generated** from the FastAPI OpenAPI schema. Change the
Pydantic models, then run:

```bash
.venv/Scripts/python.exe backend/scripts/generate_types.py
```

`test_generated_types.py` fails whenever the committed file and the live schema
disagree. Do not hand-edit it.

**Dependency locks are part of the cross-machine behaviour.** `setup.ps1` uses
`npm ci` and `backend/requirements.lock.txt`; changing only a broad range in
`backend/requirements.txt` changes no fresh install. Update the environment from
the direct requirements, run the full suite, then regenerate and commit the
lock deliberately. `package-lock.json` receives the same treatment: change it
through npm and never replace `npm ci` with `npm install` in setup.

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

New Lab evaluations resolve and pin each Custom Extractor revision when metadata
is available. Legacy or metadata-denied runs retain unknown versions. A new run
also stores a fingerprint and a snapshot of the supplier register and supplier
rules, and a retry replays that snapshot. A run from before the snapshot
existed still uses the live tables, and the Lab says so. Remote processors
other than a pinned Custom Extractor version are still whatever Google serves
at retry time.

New evaluations freeze their input PDF bytes and labels in a manifest and the
hash-addressed `backend/data/evaluation-inputs` folder. Retry and historical
preview read that snapshot, never the current dataset. Legacy runs without a
manifest cannot be retried. Keep that distinction when changing the API or UI.
Usage completeness is separate from a successful extraction: historical or
retried runs can lack billable counters. Do not turn those missing facts into a
zero or a complete cost estimate.

**Ports do not establish process ownership.** `start.ps1` and `stop.ps1` use
`scripts/process-safety.ps1` before adopting or stopping a listener. A foreign
service on 3000 or 8000 is an error with its PID, never something DocuFlow may
terminate. Keep `backend/tests/test_powershell_scripts.py` green when changing
the lifecycle scripts.

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

## How this codebase is written

These are conventions the existing code follows. Match them.

**Comments say why, and cite what was measured.** Not what the line does — that
is visible. What the obvious alternative was and what happened when it was
tried. Where a number is chosen, say what it was chosen from.

**Error messages state facts and stop.** What happened, and nothing else — no
recommendation, no "try X instead", no guess at a cause. Deciding what to do
about it is the reader's. The line is between naming a thing and prescribing a
remedy: *"No Gemini API key is configured. Add one in LLM"* names where that
setting lives, which is a fact about the app; *"Download the key again"*
prescribes a fix for a cause nobody diagnosed.

**Never state what cannot be known.** The app does not predict how long a run
will take or how many pages a document has before reading it. Where there is no
measured history, say nothing rather than invent a figure.

**Tests are named as sentences about behaviour**, with a docstring naming the
failure they prevent — `test_a_pipeline_that_calls_no_model_does_not_wait_for_one`,
not `test_uses_model`. Several tests exist only to record something that was
measured against a live service, and their docstrings say so.

**Ask what a pipeline does; do not assume it.** Whether pages leave the machine,
and whether a model is called at all, are read from the steps
(`lib/pipeline-steps.ts`, `uses_model` in `backend/app/pipeline/definition.py`).
Both were assumed once, and both assumptions were wrong for the same pipeline:
it waited for a model it never calls, and called itself private processing while
uploading every page to Google.

**This app is never deployed.** It is built once and served from disk beside a
local backend. It was scaffolded from a template carrying a Cloudflare Worker
entry point with D1 and R2 bindings, none of them ever bound to anything; that
apparatus and its 145 MB of toolchain were removed. Do not reintroduce a
deployment target.

## Layout

```text
app/          React components; page.tsx is the shell and every section's host
lib/          Frontend logic worth testing on its own, and generated types
tests/        Node test runner, one file per lib module
backend/app/
  main.py         the FastAPI app; endpoints live in api/routes
  domain/         Pydantic models — the contract the frontend types come from
  pipeline/       Step definitions, the compiler, and the steps themselves
  services/       LM Studio, Gemini, Document AI, master data, supplier rules
  evaluation/     Datasets, scoring, run storage
backend/tests/    pytest, one file per concern
```
