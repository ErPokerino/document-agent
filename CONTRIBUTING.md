# Contributing to DocuFlow

For everyone who changes this repository — people and coding agents (Codex,
Claude Code, Cursor) alike. Agents also read [AGENTS.md](AGENTS.md), which
points back here.

## Before you start

- Set up and run the app as in [docs/development.md](docs/development.md).
- Read [docs/architecture.md](docs/architecture.md) for where things live.
- Several people and agents work on `main`. Pull before you start, keep a
  change to one subject, and push when it is done: work that exists only on one
  machine is work nobody else can build on.

## Two long-lived branches

- **`main`** is DocuFlow as it runs on a developer machine.
- **`cloud`** is what is deployed to Google Cloud: `main` plus what a cloud
  deployment needs (`deploy/gcp/`, and code that is active only when its
  `DOCUFLOW_*` variables are set, so it runs locally exactly as `main` does).

Work for both lands on `main`; merge `main` into `cloud` regularly, never the
other way round by accident. A change that only the deployment needs lands on
`cloud`. Anything on `cloud` that is useful locally too — the job runner, the
PostgreSQL support, the model server provider — is configuration-gated so it
can move to `main` in one merge when the team decides to. Deploy only from
`cloud` ([deployment](docs/deployment.md#google-cloud)).

## Making a change

1. **Branch** from `main` for anything larger than a fix (`feature/…`, `fix/…`,
   `docs/…`), and open a pull request; small fixes may go straight to `main`.
2. **Test** with `npm test`; add `npm run build` when the frontend changed. CI
   runs both, plus the container images, on every push and pull request.
3. **Regenerate** `lib/types.ts` with `npm run types:generate` whenever a model
   in `backend/app/domain/` changes; never edit it by hand.
4. **Document** the change in the same commit ([below](#keeping-the-documentation-current)).
5. **Commit** with a message whose first line says what the change does for
   someone using DocuFlow, in the imperative ("Let a pipeline send only
   textless PDFs to OCR"), and whose body says why. Agents add their
   co-author line.

## Keeping the documentation current

Documentation lives beside the code and changes in the same commit as the
behaviour it describes. Where to write:

| You changed… | Update |
|---|---|
| What a user can do or see in a section | the page for that section in `docs/features/` |
| How the system is put together, a module, a store | `docs/architecture.md` |
| Setup, commands, tests, CI, a trap that cost you time | `docs/development.md` |
| Configuration, containers, anything about running in a cloud | `docs/deployment.md` |
| A decision with alternatives that were rejected | a new record in `docs/decisions/` |
| Work decided but postponed, or a next step | `ROADMAP.md` |
| A rule for how code here is written | this file |

`README.md` stays a short entry point; it links to the pages above rather than
repeating them. A page describes what is true now; history belongs in commits,
decision records and `docs/history/`.

## How this codebase is written

These are conventions the existing code follows. Match them.

**Comments say why, and cite what was measured.** Not what the line does — that
is visible. What the obvious alternative was and what happened when it was
tried. Where a number is chosen, say what it was chosen from. A figure that was
not measured is not written as if it were.

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

**Prefer a map typed by a generated union over a map keyed by `string`.** Adding
a step kind or a format then fails the type check everywhere it needs a name.

**Stay portable.** No cloud SDK outside its adapter module, no path or origin
written into code where `backend/app/config.py` can supply it, no stored format
that only one provider reads, no pickles. See [docs/deployment.md](docs/deployment.md).

**One place per subject.** Backend: an endpoint in `api/routes/<subject>.py`, a
model in `domain/<subject>.py`, logic in the package for its subject. Frontend:
a component in the folder of its section, a pure function in `lib/` with a test
in `tests/`.
