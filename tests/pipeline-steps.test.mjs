import assert from "node:assert/strict";
import test from "node:test";

import { isPdfTextFallback, readsInTheCloud, uploadsOnlyScans, usesModel } from "../lib/pipeline-steps.ts";

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

const reader = { kind: "read_pdf_text", config: { feeds_model: true } };
const fallback = { kind: "document_ai_ocr", config: { processor_ref: "ocr", only_without_pdf_text: true } };
const ocr = { kind: "document_ai_ocr", config: { processor_ref: "ocr" } };

test("an OCR step is a fallback only when it is set to read PDFs without text", () => {
  assert.equal(isPdfTextFallback(fallback), true);
  assert.equal(isPdfTextFallback(ocr), false);
  assert.equal(isPdfTextFallback({ kind: "document_ai_layout", config: { only_without_pdf_text: true } }), false);
});

test("a pipeline whose only Document AI step is the fallback uploads only scans", () => {
  assert.equal(uploadsOnlyScans([reader, fallback, { kind: "llm_extract", config: {} }]), true);
});

test("any other Document AI step means every document is uploaded", () => {
  assert.equal(uploadsOnlyScans([reader, fallback, { kind: "document_ai_extract", config: {} }]), false);
  assert.equal(uploadsOnlyScans([ocr, { kind: "llm_extract", config: {} }]), false);
});

test("a pipeline with no Document AI step makes no claim about scans", () => {
  // It uploads nothing at all, which is a stronger statement made elsewhere.
  assert.equal(uploadsOnlyScans([reader, { kind: "llm_extract", config: {} }]), false);
});
