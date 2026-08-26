import assert from "node:assert/strict";
import test from "node:test";

import { readsInTheCloud, usesModel } from "../lib/pipeline-steps.ts";

test("extraction by a model calls the model", () => {
  assert.equal(usesModel(["render_pages", "llm_extract"]), true);
});

test("extraction by the Custom Extractor calls no model", () => {
  // The whole point: this pipeline was made to wait for a model it never uses.
  assert.equal(usesModel(["document_ai_extract"]), false);
});

test("supplier rules count, because one of them may ask the model", () => {
  // Which supplier a document is from is not known until the run is under way,
  // so a prompted rule cannot be ruled out in advance.
  assert.equal(usesModel(["document_ai_extract", "master_data_lookup", "supplier_rules"]), true);
});

test("a regex or a register lookup is not a model", () => {
  assert.equal(usesModel(["document_ai_ocr", "regex_refine", "master_data_lookup"]), false);
});

test("every Document AI step uploads the pages", () => {
  for (const kind of ["document_ai_ocr", "document_ai_layout", "document_ai_extract"]) {
    assert.equal(readsInTheCloud([kind]), true, kind);
  }
});

test("rendering pages locally uploads nothing", () => {
  assert.equal(readsInTheCloud(["render_pages", "llm_extract"]), false);
});
