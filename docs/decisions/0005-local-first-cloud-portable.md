# 0005 — Local first, deployable on any cloud

**Supersedes** the earlier rule "this app is never deployed", which was written
when the template's Cloudflare Worker apparatus was removed.

**Context.** DocuFlow started as a local proof of concept. It will be deployed,
first on Google Cloud, and must not become dependent on one provider; more
people will work on it.

**Decision.** The app ships as plain OCI images configured by `DOCUFLOW_*`
variables. Every external service sits behind one adapter module. Stored
formats are provider-neutral. Local development keeps working without Docker.

**Alternatives.** A provider-specific deployment (App Engine, Cloud Functions,
a Worker) — rejected: it ties the code to one platform's runtime model.

**Consequences.** The gaps that remain — authentication, a job queue, a
database and object-storage interface, generic reader kinds — are listed in
`docs/deployment.md` and scheduled in `ROADMAP.md`.
