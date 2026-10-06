# Model Garden partners and per-attempt charges

Status: accepted on 2026-10-06.

## Context

Cloud deployments already call Gemini through Google identity. Partner models
have different protocols, locations, cache accounting and quotas. A run's
successful token totals miss paid failures, retries and multiple model steps.

## Decision

Use provider `model_garden` with publisher-specific HTTP transports inside one
adapter. Claude uses Messages/rawPredict with adaptive thinking and structured
JSON; Grok uses Google's OpenAI-compatible endpoint with strict JSON Schema.
Authentication is GCP OAuth; no Anthropic or xAI API keys are stored.

Default Claude location is EU; Grok is Global and remains marked Preview.
No fallback changes the model or location. A Lab profile pins project,
location, output limit and Claude effort for workers and retries.

Persist every attempt before calling the provider and finalize it even when
response validation fails. Store provider usage, request id, HTTP status,
tariff version, location and cost; never prompts or responses. Unknown usage
is unknown cost. HTTP 4xx/5xx have zero model charges under Google's published
rule; network disconnects have unknown charges. Retry only 429/503, at most
three attempts, with backoff. Grok reservations are shared through SQLite or
PostgreSQL, across the API and worker processes.

Prices are the Google Model Garden pay-as-you-go table checked on 2026-10-06,
in USD per million tokens. Input, output, cache reads and cache writes are
separate. Grok's context tier includes cached input and applies to the entire
request; reasoning is separate in Google's response and included exactly once
using `total_tokens - prompt_tokens`. Claude cache TTLs without a breakdown,
and unpublished long-context cache rates, remain incomplete estimates.
Document AI page prices are also snapshotted in partner runs. Existing Gemini
and local histories retain their prior accounting behavior.

Amended 2026-10-06: availability is checked, not assumed. Verify asks each
hosted model, Gemini included, for one token in the location on screen and
keeps the answer per model and location in the backend process. Gemini's
Vertex AI location can be chosen in LLM and is recorded on the run, since a
preview model may exist in `global` only. Claude and Grok have separate output
limits. LLM shows one card per publisher with the same structure.

Amended again 2026-10-06, for uniformity: Gemini, Claude and Grok are all
named and reached as Vertex AI. Every publisher has the same controls
(location, reasoning effort, output limit; Grok now sends `reasoning_effort`,
Gemini gains an output limit) and the same rates: Google's published table in
code, per model, location and date, which LLM can override per
`model@location`. Gemini moves onto the per-attempt ledger, so its cost
follows its location and retries like the partners'. The alternative, keeping
Gemini's display-time rates beside per-attempt partner rates, would have
shown two pricing behaviours on one page; runs recorded before keep theirs.

## Alternatives

Direct partner keys would bypass Google billing and the requested platform.
Reusing Gemini's payload would mix incompatible schemas. Repricing stored
attempts with current settings would change history. Blindly using OpenAI's
reasoning convention would undercharge the observed Grok response.

## Consequences

The application database gains an additive `model_usage` table. Failed and
cancelled attempts survive independently of successful extraction rows.
Estimates are auditable through authenticated usage endpoints and JSON export;
GCP billing remains authoritative. Grok may wait for quota reservations.
Terms, project billing, publisher access and model quota remain deployment
prerequisites distinct from API enablement and IAM.

Source: [Google Model Garden pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)
and [Grok reasoning](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/grok/capabilities/reasoning).
