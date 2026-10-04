# Roadmap

Work that has been decided on but deliberately postponed, with the reasoning
that led there. Kept in the repository rather than in a chat so the decisions
outlive the conversation that produced them.

Anything already built is in the README, not here.

## Next

Nothing outstanding. The items below are decided and deliberately waiting.

## Later

### Branches and parallel execution in the pipeline canvas

The visual editor presents the existing sequential engine as a flowchart. Its
connections come from step order rather than from a separate editable graph, so
opening and saving an old pipeline preserves its execution contract. A conditional
OCR node still runs in sequence and skips PDFs with native text when configured.

Free connections and parallel branches would need an execution model, explicit
input/output contracts and rules for merging results. Keep them out of the canvas
until the engine supports them; a diagram must describe what will actually run.

### Several methods per field, and a strategy that picks

The largest architectural idea on this list, and the one that reshapes
everything else.

Today a field gets its value from exactly one place: the model, or a regex, or
a register lookup, whichever step in the pipeline wrote it last. On the real
project this is modelled on, an entity can be recognised by **several methods at
once** — a Document AI parser, a nearest-neighbour prediction, a model, a rule —
each producing a candidate with its own confidence. A **strategy** then chooses
the final value: by priority between methods, or by comparing the confidences,
or both.

That is a different shape from the current pipeline, and a better one. A step
today overwrites; a method would *propose*. What it buys:

- a field can be recognised by whatever actually works for it, without one
  method having to win everywhere;
- the strategy becomes the place where "which source do we trust for this
  field" is stated once, rather than being implicit in step order;
- every method's candidate is recorded, so it can be measured — which method
  was right, how often, per field. That is the same question Lab already asks
  about whole approaches, asked one level down.

Built (README, *Several methods per field*): candidates are recorded by the
engine, a Resolve candidates step chooses, and the Lab scores each method and
the oracle and can re-resolve a stored run. Still open: candidates from steps
that run side by side rather than in sequence, which needs the branching
engine described above, and a strategy learned from Lab history instead of written.

### Nearest neighbour as one of those methods

Not only for deciding what can pass without a person. On the real project it
predicts **categorical fields** generally — `id_subject`, `currency`, and others
this POC does not have yet.

The mechanism:

1. embed the document text as a TF-IDF vector;
2. find the nearest already-processed document by cosine similarity;
3. take that neighbour's categorical fields as the prediction for the new one.

A KNN over TF-IDF embeddings, and it works well in practice. The same neighbour
also answers the auto-validation question — if it was extracted correctly, the
new document can pass without a person; if not, it goes to review — but that is
one use of the prediction rather than the point of it.

Preferred over a threshold on model-stated confidence, which is not calibrated:
whether *high* means high depends on the model.

Built as the first kind of trained model (README, *Models trained on the
datasets*), and as a step for now. It becomes one method among several once
candidates exist. Test-Dataset has one document per supplier, so its
leave-one-out accuracy is 0 for `id_subject` by construction: a neighbour
search needs several labelled documents per class before it can mean anything.


### Document types and flows

Today there is one implicit type, invoice, and its entities, prompts, pipeline
and register are global settings. More types makes those per-type, reaching
into settings, storage, Datasets, Lab comparisons, Master Data and most of the
UI.

The type is **chosen by the user**, not detected. Chosen is most of the value
and is the prerequisite for detection anyway; detection can arrive later as one
more step in the vocabulary that already exists.

Postponed until the new document classes are actually needed. Decide what the
runs and datasets already recorded become before starting.

### Splitting compound PDFs

One PDF may hold several documents, and the app deliberately refuses to merge
page extractions into one incoherent record. A splitting step would emit one
record per document, which is what makes the app usable on a scanned batch
rather than on single files.

Expected approach: a Document AI **custom splitter** processor, alongside the
OCR and Layout processors already configured.

### A-priori cost and time estimate

Before a run starts, state what it is likely to cost and how long it will take,
from the measured history of that model on that pipeline. Analytics already
computes those per-document figures. With no history for a combination, say
nothing rather than invent a number.

### Packaging for real portability

Setup is one command, but it still wants Python, a virtual environment, Node
and a build. A packaged runtime would remove all of that.

To keep in mind throughout rather than to build in one go: it collides with the
local dependency, since LM Studio is installed per machine and cannot be shipped
with the app.

One step already taken, in that spirit: the Cloudflare Worker entry point and
its D1 and R2 bindings, inherited from the template this was scaffolded from and
never bound to anything, are gone — along with 145 MB of toolchain that every
machine was installing to deploy an app that is served from disk beside a local
backend.

### Splitting main.py into routers

Done. `main.py` mounts one router per section under `backend/app/api/routes`,
and the shared stores and helpers live in `backend/app/api/deps.py`.

### Pipeline graph in the UI

A drawn graph of the selected pipeline. Low value while pipelines are linear and
three to six steps long — the sentence already shown carries the same
information. Worth revisiting only once flows branch, as part of document types.

## Proposed next work following the September review

These are proposals awaiting prioritisation, not implemented features.

### Native PDF text as a pipeline reader

Done as the `read_pdf_text` step. A document with no embedded text on any page
it may read is refused, and a page without text is named in the text the model
is given. It is a reader to measure against OCR, not a default: reading order,
stale embedded OCR and tables can all differ from what the page shows.

Mixed scanned and native files are handled by an OCR fallback the pipeline
states, never an automatic one: a Document AI OCR step placed after Read PDF
text and set to *Only a PDF that carries no text of its own*
(`only_without_pdf_text`) reads, uploads and bills only the documents Read PDF
text found no text on. Automatic was decided against because it would make a
pipeline that reads on this machine start sending scans to Google on its own.
The fallback is per document, not per page: a PDF with text on some pages still
tells the model which pages carry none. The compiler refuses a fallback with no
Read PDF text before it, or with a step that fills entities between the two.

### Further Lab comparison work

The implemented multi-select filters, history pagination, extractor identities
and Pareto presentation are documented in README. Remaining work:

- Give historical analysis its own space by moving Run a test into a New
  evaluation action and offering Runs, Analytics and Compare as peer views.
- Apply field exclusions consistently to thresholds, Runs and Analytics.
  Accuracy thresholds currently use the unadjusted score, and Analytics does
  not expose the exclusion control available in Runs.
- Done: a configuration fingerprint of dataset hashes and labels, prompts,
  the complete pipeline, the model profile, the supplier register and supplier
  rules. Analytics groups on it. Runs from before the column existed stay on
  the coarser grouping.
- Done for experiments: cells are compared on the documents every finished
  cell scored, with bootstrap intervals and a paired difference from the best.
  Still open for runs compared outside an experiment, and for label changes
  between runs.
- Consider a logarithmic time axis for wide runtime ranges and explain missing
  cost measurements directly in the chart.
- Add per-request context-tier accounting before enabling automatic Gemini
  3.1 Pro Preview rates. Summed run token counts cannot select a request's tier.

### Resource catalog boundaries

Processors registers existing Google resources; creating, training, deploying and
changing Google's default version remain in Google Cloud. Connection and pricing
are grouped with the catalog; metadata access is distinct from process access.
LLM keeps its capability and size filters inside Local/API views. Per-step LLM
selection and multiple credential profiles are separate future changes, not
implied by a processor catalog. Document AI pricing currently remains per type;
version-specific pricing would require matching usage attribution.
