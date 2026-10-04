# Working on DocuFlow — for coding agents

DocuFlow extracts structured fields from invoice PDFs and is a bench for
finding the best configuration to do it: composable **pipelines** of steps, a
**Lab** that measures them over labelled datasets, **experiments** that compare
them, and **models** trained on the labelled history. A step declares what it
needs and what it leaves behind, and the compiler refuses a pipeline whose
steps cannot be satisfied in order.

Read, in this order:

1. [CONTRIBUTING.md](CONTRIBUTING.md) — workflow, the conventions code here
   follows, and which document to update for which change.
2. [docs/architecture.md](docs/architecture.md) — what lives where.
3. [docs/development.md](docs/development.md) — commands, tests, and the
   *Known traps* that have each cost a day.

## Rules

- **Several people and agents share this repository.** Pull before you start,
  keep a change to one subject, scope wide refactors carefully, and push when
  done.
- **Run `npm test` before you call a change finished**, and `npm run build`
  when the frontend changed. Report failures as they are.
- **Never assume `backend/data` exists**: no settings, model, credentials or
  history in a fresh clone.
- **Never hand-edit `lib/types.ts`**: change `backend/app/domain/` and run
  `npm run types:generate`.
- **Change locks deliberately** (`backend/requirements.lock.txt`,
  `package-lock.json`); never replace `npm ci` with `npm install`.
- **Keep DocuFlow portable.** It will be deployed on more than one cloud,
  Google Cloud first. No cloud SDK outside its adapter, no hard-coded paths or
  origins, no pickles ([docs/deployment.md](docs/deployment.md)).
- **Write decisions down where they outlive the conversation**: the docs page
  for the subject, a record in `docs/decisions/`, or `ROADMAP.md` — not only a
  commit message.
- **After building, restart with `.\restart.ps1`**: a build under a running
  server leaves the page dead while it still answers 200.
