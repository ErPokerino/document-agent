# Pipelines

How a document is processed: the steps, the visual editor, and how several methods propose a value for one field.

## Visual pipeline editor

**Pipelines** opens saved definitions as a connected flow from PDF input to
extracted fields. Existing pipelines need no migration: the canvas is a view of
the same ordered steps, with all processor bindings, versions and rules intact.
Select a node to edit its settings; use a **+** on a connection to insert a step
there, or search the grouped step picker. **Earlier / Later** changes execution
order, while dragging nodes only arranges the current canvas. Layout positions
are temporary and are reset when opening a flow or changing its step order.

The canvas supports pan, zoom, fit and expansion. A compact order strip selects
and centres any step in a long flow. Conditional OCR carries an explicit badge;
invalid steps are marked and their compiler messages appear in the inspector.
Saving and selecting **Use** remain separate actions.

The visual editor uses React Flow, with a pinned version in the npm lockfile.
Connections follow execution order automatically; arbitrary branches, parallel
execution and cycles are not supported by the pipeline engine.

## Several methods per field

Every step that writes a field leaves a **candidate**: its method (the step
kind, or `trained: <model>` for a trained model, numbered when a pipeline
repeats a kind), the value, its confidence and score. The engine records them
by comparing each field before and after a step: a field the step wrote is a
new object even when the value is unchanged, so a second method that agrees is
recorded as agreement rather than lost. Steps that only choose or only mark a
field empty propose nothing.

Without further steps the last candidate is the value, which is what step order
always meant. A **Resolve candidates** step states the choice instead, for every
field or per field:

- *last* — the old rule, explicitly;
- *priority* — the first listed method with a usable value; an unlisted method
  is not consulted, and an optional score floor passes over a weak prediction;
- *most confident* — highest confidence band, then score, later steps winning
  ties;
- *agreement* — the value most methods proposed, each counted once; an even
  split leaves the field empty with the reason, and a unanimous answer from two
  or more methods is high confidence.

A Lab run stores each field's candidates and reports, per field, every
method's accuracy, the chosen value's accuracy and the **oracle** — the share
of documents where at least one method was right, the ceiling for any rule over
these methods. **Try a rule on this run** resolves the stored candidates again
under another rule and scores it without reading a document or calling
anything; the run itself is not changed.

## Reading the text a PDF already carries

The `read_pdf_text` step reads the text a native PDF carries, with word
positions, on this machine. A document with no embedded text on any page it may
read is refused, and a page without text is named in the text the model is
given. It is a reader to measure against OCR, not a default: reading order,
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
