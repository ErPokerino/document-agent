# Roadmap

Work that has been decided on but deliberately postponed, with the reasoning
that led there. Kept in the repository rather than in a chat so the decisions
outlive the conversation that produced them.

Anything already built is in the README, not here.

## Next

### Provenance highlighting

Show where on the page each extracted value came from, so a reviewer confirms
by glancing instead of re-reading.

Coordinates are **found, not asked for**. Document AI already returns every
token with its bounding box; once the model answers `supplier_name: "ACME
SUPPLIES LTD"`, that string is located in the token stream and the matching
boxes are unioned. Asking the model to return coordinates would multiply output
tokens and invite the same copying failures the value ceiling closed.

Two limits accepted on purpose:

- a string occurring several times in a document is ambiguous, and the first
  match is taken;
- a value the OCR never saw cannot be highlighted, which includes anything the
  model inferred rather than read.

An OCR step must therefore be addable to a pipeline **purely to supply boxes**,
even when extraction is done by a multimodal model that never reads its text.

### Run-to-run regression diff

Compare two chosen runs document by document and field by field: what changed
verdict, what improved, what regressed. An option the user selects, not
something that happens automatically. Aggregates hide the case that matters —
a prompt edit that fixes two documents and breaks two others reads as no change.

### Supplier-specific rules layer

After `id_subject` resolves, a per-supplier rule set corrects or re-extracts
named fields.

`id_subject` is what the layer keys on, **not** `supplier_name`: several
spellings of a supplier legitimately resolve to the same internal id, and the
id is the thing that is either right or wrong. Accuracy of the underlying
extraction is the user's judgement, not a gate on exposing the feature — the
figures on the bench come from small local models, and a capable one rarely
misses.

Rules should be able to be deterministic as well as prompted. The most valuable
supplier rules are often regexes or fixed values (*this one prefixes the number
with `Ns. Rif.`, this one writes dates day-first, this one is always EUR*), and
a second model call should be paid for only when a rule genuinely needs one.

The Lab has to be able to run with and without the layer, or there is no way to
tell whether it earned its cost.

## Later

### Auto-validation by nearest neighbour

Deciding which documents can pass without a person. The approach in use on a
real project the author works on, and the one to adopt here:

1. embed the document text as a TF-IDF vector;
2. find the nearest already-processed document by cosine similarity;
3. if that neighbour could have been auto-validated — it was extracted
   correctly — auto-validate the new one; otherwise send it to human review.

A KNN over TF-IDF embeddings, and it works well in practice. Preferred over a
threshold on model-stated confidence, which is not calibrated: whether *high*
means high depends on the model.

Postponed until there is enough processed history for a neighbour search to
mean anything.

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

### Pipeline graph in the UI

A drawn graph of the selected pipeline. Low value while pipelines are linear and
three to six steps long — the sentence already shown carries the same
information. Worth revisiting only once flows branch, as part of document types.
