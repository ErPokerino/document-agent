# Roadmap

Work that has been decided on but deliberately postponed, with the reasoning
that led there. Kept in the repository rather than in a chat so the decisions
outlive the conversation that produced them.

Anything already built is in the README, not here.

## Next

Nothing outstanding. The items below are decided and deliberately waiting.

## Later

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

The pipeline vocabulary would need candidates alongside values: a step writes
into a field's candidate list rather than over its value, and one final step
resolves them. Existing steps become single-candidate methods, so nothing has
to change at once.

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

Postponed until there is enough processed history for a neighbour search to
mean anything, and best built after the multi-method shape above, since it is a
method rather than a step.


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

Fifty-eight endpoints in one 1,750-line module. They are grouped by subject and
the groups are now marked, so the file is navigable, but changing one endpoint
still means loading all of it — which costs an agent its context and makes two
people working in different areas collide in the same file.

`APIRouter` per section, along the boundaries the markers already draw. Deferred
rather than dismissed: it touches every endpoint at once, and this repository
has more than one agent working in it, so it wants a moment when nothing else is
in flight.

### Pipeline graph in the UI

A drawn graph of the selected pipeline. Low value while pipelines are linear and
three to six steps long — the sentence already shown carries the same
information. Worth revisiting only once flows branch, as part of document types.
