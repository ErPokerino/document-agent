import assert from "node:assert/strict";
import test from "node:test";

import { cellAt, gridColumns, gridRows, planGrid, planSummary, sendsImages, signedPoints } from "../lib/experiments.ts";

const vision = { name: "Vision", steps: [{ kind: "render_pages" }, { kind: "llm_extract" }] };
const text = { name: "Text", steps: [{ kind: "read_pdf_text" }, { kind: "llm_extract" }] };
const noModel = { name: "Extractor", steps: [{ kind: "document_ai_extract" }] };
const seeing = { id: "a", name: "A", provider: "lm_studio", vision: true, capabilities_known: true };
const blind = { id: "b", name: "B", provider: "lm_studio", vision: false, capabilities_known: true };

test("the preview pairs every pipeline with every model, and a modelless pipeline runs once", () => {
  const cells = planGrid([text, noModel], [seeing, blind]);

  assert.deepEqual(cells.map((cell) => [cell.pipeline, cell.model, cell.state]), [
    ["Text", "a", "runs"], ["Text", "b", "runs"], ["Extractor", null, "once"],
  ]);
});

test("a pipeline that sends images is not paired with a model that cannot read them", () => {
  const [, skipped] = planGrid([vision], [seeing, blind]);

  assert.equal(skipped.state, "skipped");
});

test("a model whose capabilities were not reported is not assumed blind", () => {
  const [cell] = planGrid([vision], [{ ...blind, capabilities_known: false }]);

  assert.equal(cell.state, "runs");
});

test("an image is sent only when page rendering comes before the model call", () => {
  assert.equal(sendsImages(vision.steps), true);
  assert.equal(sendsImages([{ kind: "llm_extract" }, { kind: "render_pages" }]), false);
});

test("the summary counts runs, extractions and skipped cells before anything starts", () => {
  assert.equal(planSummary(planGrid([vision, noModel], [seeing, blind]), 10), "2 runs · 20 document extractions (10 labelled documents each) · 1 cell skipped");
});

test("the result grid puts models across and pipelines down, no-model column last", () => {
  const experiment = {
    cells: [
      { index: 0, pipeline: "Extractor", provider: "none", model: "Not used", status: "completed", skipped: null, error: null, run: null },
      { index: 1, pipeline: "Text", provider: "lm_studio", model: "a", status: "completed", skipped: null, error: null, run: null },
    ],
  };

  assert.deepEqual(gridColumns(experiment).map((column) => column.label), ["a", "No model called"]);
  assert.deepEqual(gridRows(experiment), ["Extractor", "Text"]);
  assert.equal(cellAt(experiment, "Text", "lm_studio\u0000a").index, 1);
});

test("a difference is shown in percentage points with its sign", () => {
  assert.equal(signedPoints(-0.0512), "−5.1 pt");
  assert.equal(signedPoints(0), "±0.0 pt");
});
