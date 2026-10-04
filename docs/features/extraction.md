# Extraction: fields, readers and corrections

What a document is asked for, how each value is read and located, and the corrections applied afterwards.

## What one extraction does

- PDF upload up to 20 MB;
- side-by-side PDF preview of the uploaded document during review;
- one vision-model call containing the first pages allowed by the configured page maximum;
- explicit cut notice showing processed pages and total pages;
- persistent model and pipeline selection;
- automatic discovery and periodic refresh of installed models, vision or text-only;
- explicit single-model `Load & warm up` phase with separate load and warm-up timing;
- a reproducible local-model profile (8,192 context, one parallel request,
  fixed evaluation settings and seed) rather than LM Studio UI defaults that
  vary from one PC to another;
- immediate cancellation of a Workspace extraction or Lab run, including the
  document currently waiting on the model;
- composable pipelines: page rendering, Document AI OCR and Layout Parser, the model call, per-field regex rules and master-data lookup, with a per-pipeline page limit;
- editable system, extraction and confidence prompts;
- configurable entities with name, format and description, each either read from the document or derived by a pipeline step;
- qualitative `low`, `medium` or `high` confidence for every value;
- field-tolerant validation: one invalid value is set to `null/low` without discarding valid fields;
- editable review fields, including missing values, with undo and manual-edit tracking in the JSON export;
- initial schema with `date`, `document_number`, `supplier_name`, `currency` and `total_amount`;
- JSON constrained by JSON Schema and validated with Pydantic;
- JSON export;
- highlighting of where each extracted value sits on the page, from OCR
  tokens or straight from the Custom Extractor, with zoom;
- extraction by a Google Custom Extractor as an alternative to a language
  model, with the processor's own confidence and the position of each value;
- per-supplier corrections applied after the register identifies the supplier:
  a fixed value, a pattern over what the page said, or one more model call
  about named fields alone;
- comparison of two runs field by field, to see what one change actually
  moved;
- a data-flow note on every run stating where the pages actually go, read from
  the pipeline's steps rather than from which model is selected: a pipeline
  built only from local steps keeps them on the machine, any Document AI step
  uploads them to Google, and a hosted model is named only when the pipeline
  actually calls one.

## Categorical fields

A field of format **Category** holds one class: a document type, a cost centre,
an internal supplier id. Its vocabulary is either:

- **closed** — the classes are listed in Extraction. A local model and Gemini
  receive the list as an `enum`, so they cannot answer outside it; the Custom
  Extractor is asked to `DERIVE` the class, since a class is decided about the
  document rather than quoted from it. An answer or a label that differs only
  in case or spacing takes the vocabulary's spelling; anything else is refused.
- **open** — no list. Any well-formed class is accepted, and the values already
  labelled in any dataset are offered while typing (`/api/label-values/{field}`).
  This is the shape a nearest-neighbour model needs: it answers with classes
  the labelled history contains.

Fields can be added at any time; nothing assumes a fixed set.

A Lab run scores each categorical field as a classifier as well as by accuracy:
precision, recall and F1 per class, their macro average (accuracy can be high
while a rare class is never found), a confusion matrix in which `(none)` is an
answer withheld, and a coverage curve — accepting only answers at or above a
threshold, how many documents pass and how many of those are right. The curve
follows the step's own score when every answer has one (a similarity does) and
the confidence band otherwise, which gives at most three points. Scores are
stored per field and exported in the CSV.

## Where a value came from

The model is never asked for coordinates: asking would multiply output tokens
and invite the same copying failures a small model already makes, and a wrong
rectangle is worse than none because it looks authoritative. Document AI already
returns every token with its box, so the value the model answered is located in
that token stream and the matching boxes are unioned.

The page is shown as an image rather than in the PDF viewer, because nothing
outside that viewer can know where it put the page, so nothing can be laid over
it accurately. Coordinates are normalized, and hold at any size.

An OCR step can be added to a pipeline **purely to supply positions**, without
its text being given to the model — which is how a multimodal model can read
the picture itself and still have its answers highlighted. The choice is on the
step in Pipelines.

Two limits are deliberate. A string that occurs several times in a document is
ambiguous, and the first occurrence is taken. A value the OCR never saw cannot
be highlighted at all, which includes anything the model inferred rather than
read, and anything derived from a register.

## Extraction without a model

A Custom Extractor reads the configured fields itself, so a pipeline built on
it needs no LLM extraction step at all — and nothing in the app waits for a
model such a pipeline will never call. It used to: every run held until the
selected model was loaded and warm, which on a Custom Extractor pipeline cost
minutes and several gigabytes to sit idle while Google did the reading, and on a
machine with no model at all made the pipeline unrunnable. Whether a pipeline
calls a model is now read from its steps, and supplier rules count, because one
of them may be an instruction to ask the model again.

Four more things follow.

**The schema travels with the request.** A generative Custom Extractor accepts a
`schemaOverride` per call, so DocuFlow sends the fields it wants every time
rather than editing the processor's stored schema. Writing Extraction's fields
into the processor whenever someone edited them would make a remote resource
shadow a local one, with two ways to fall out of step and a failed write leaving
them disagreeing silently. This way Extraction stays the one place fields are
defined, and the processor is configured once and left alone.

Each field carries the description written in Extraction, which is what the
processor reads and the difference between a usable answer and a wrong one:
asked for a currency with no description this processor answered `$`, and told
the code was ISO 4217 it answered `USD`. Descriptions need the `v1beta3`
endpoint — `v1` rejects the field outright — so the Custom Extractor alone uses
it, while OCR and the Layout Parser stay on `v1`.

**Each field says how it is to be answered**, and it is the most consequential
line in the schema. `EXTRACT` points at a span on the page, so it can only
return what is printed and cannot be asked for a form the document does not
carry: told a currency must be an ISO 4217 code, an `EXTRACT` field on an
invoice showing only `S$` returned nothing — and a field it cannot satisfy takes
others down with it, which is how the date went missing from the same response.
`DERIVE` lets it work the value out; the same field, the same description, as
`DERIVE`: `SGD`. So dates and currencies are derived and everything else is
extracted, and what a field may be told follows from which it is. A derived
value has no span on the page, so it also has no highlight box.

What a format requires is said in one place, shared by every reader that asks:
Gemini's schema, the Custom Extractor's schema, and a local model's prompt. It
is appended only when the description does not already say it, and that is not
tidiness. A description reading "Normalize it to YYYY-MM-DD" followed by
"Format the value as YYYY-MM-DD" made this processor return **no date at all**,
three times out of three, while either sentence alone worked every time.
Repeating an instruction to a generative reader is not free.

**Confidence comes from the processor**, so nothing asks a model how sure it is.
The number is kept as well as the band the rest of the app reads.

**Boxes come with the entities**, so highlighting needs no separate OCR step and
nothing is searched for in the page text.

What does not change is validation: a currency is a three-letter code whoever
read the page, so a processor answering `$` is corrected exactly as a model
would be.

One thing about this processor is worth knowing before writing a description
for it, and it was measured rather than assumed: it is **generative**, so it
varies. The same document and the same request returned a date on one call and
not the next. What it may be asked for is settled by the method above, not by
how the description is worded.

A field the processor did not answer says so, because silence and an invoice
that genuinely lacks the value look identical otherwise.

## Confidence

Confidence is a qualitative model assessment, not a calibrated probability. Its rubric is editable in Extraction. By default:

- `high`: clearly visible, explicitly labelled and unambiguous;
- `medium`: readable but identified through context or with minor ambiguity;
- `low`: partial, conflicting, hard to read or unavailable.

The backend always normalizes a `null` value to `low` confidence.

If the model runs out of output tokens before closing the JSON object, the request
fails with an explicit output-limit message rather than a generic parse error: a
retry would only add prompt tokens and could never recover.

If a model returns a value in the wrong format, only that field is cleared and marked for review. Other valid entities remain available. A currency is stored as a three-letter ISO 4217 code, with whitespace removed and lowercase canonicalized. A symbol naming exactly one currency is read as that currency — `S$` is Singapore's and nobody else's — while a bare `$` belongs to a dozen countries and is refused, because a wrong currency on an invoice is worse than an empty one. That line used to sit at every symbol, which was right while only models read the page: a model writing `$` had chosen not to give the code. A processor that points at a span can only answer with what is printed, and documents print symbols.

## Multi-page documents

The app deliberately does not extract page blocks and merge their values. A large PDF may contain multiple invoices or document types, so merging independent extractions could create an incoherent record.

Instead, it sends the number of initial pages the pipeline allows together in one model call. The parameter count and theoretical context length are not used to choose a page limit. If the selected maximum exceeds the context actually available to the loaded model, LM Studio rejects the request and its context must be changed when loading the model.

The UI reports `pages 1–N of M`. If `N < M`, the remaining pages were not sent to the model. The complete original PDF remains available in the preview for human review.

Rendered pages are held in memory as base64 until the model answers, so a single
request is capped at a 64 MB image budget. Exceeding it fails with an explicit
message instead of exhausting the backend process.

## Rules for one supplier

Layouts repeat per supplier, and so do the exceptions: this one prefixes the
number with `Ns. Rif.`, this one always bills in euro, this one writes the date
the other way round. A general prompt cannot absorb all of that without getting
worse at everything else, so the corrections live beside the supplier in Master
Data and run in a `Supplier rules` step placed after the register lookup.

They key on `id_subject`, never the supplier's name: several spellings of one
supplier legitimately resolve to the same internal id, and the id is the thing
that is either right or wrong. A document whose supplier was not identified gets
no rules at all — inheriting somebody else's corrections is worse than applying
none.

Two kinds, deliberately separated. A fixed value or a pattern costs nothing,
cannot hallucinate, and is what most supplier exceptions actually are. A
prompted rule is one more model call, and separating them is what makes that
call happen only when there is something to ask — and then about the named
fields alone, so the rest of the extraction is left as it was.

Whether the layer earns its cost is measurable the same way everything else is:
a pipeline with the step and one without are two runs, and Lab compares them
field by field.
