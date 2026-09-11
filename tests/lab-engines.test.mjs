import test from "node:test";
import assert from "node:assert/strict";
import { engineLabel, engineDetail, engineKey } from "../lib/extraction-engine.ts";
import { approachPoints, approachDescription } from "../lib/analytics.ts";
import { emptyFilters, filterEvaluations } from "../lib/run-filters.ts";

const run = (id, model, dataset = "Invoices", engine = null) => ({ id, model, dataset, pipeline: "P", provider: "none", steps: engine ? ["document_ai_extract"] : [], extraction_engine: engine, metrics: { accuracy: 0.8 }, total_documents: 1 });

test("multiple choices use OR within a filter and AND across filters", () => {
  const runs = [run(1, "a"), run(2, "b"), run(3, "ab"), run(4, "a", "Other")];
  assert.deepEqual(filterEvaluations(runs, { ...emptyFilters, model: ["a", "b"], dataset: ["Invoices"] }).map(r => r.id), [1, 2]);
});

test("legacy Custom Extractor never borrows current model metadata", () => {
  const legacy = { ...run(1, "Not used"), steps: ["document_ai_extract"] };
  assert.equal(engineLabel(legacy), "Custom Extractor");
  assert.match(engineDetail(legacy), /Version not recorded/);
});

test("different datasets and processor revisions remain separate approaches", () => {
  const a = run(1, "Not used", "Invoices", { processor_id: "p", version: "v1" });
  const b = run(2, "Not used", "Invoices", { processor_id: "p", version: "v2" });
  assert.notEqual(engineKey(a), engineKey(b));
  assert.equal(approachPoints([a, b, { ...a, dataset: "Other" }], () => null).length, 3);
});

test("hover describes a model once and leaves the dataset to the table", () => {
  assert.equal(approachDescription({ model: "Gemma", pipeline: "OCR", dataset: "Invoices", detail: "Gemma" }), "Gemma\nPipeline: OCR");
  assert.equal(approachDescription({ model: "Custom Extractor", pipeline: "Custom Extractor", dataset: "Invoices", detail: "Document AI Custom Extractor · Version not recorded" }), "Custom Extractor\nVersion not recorded");
});


import { compactExtractorVersion } from "../lib/extraction-engine.ts";

test("the extractor header shortens known versions without inventing unknown metadata", () => {
  assert.equal(compactExtractorVersion("pretrained-foundation-model-v3.1-lite-2026-07-15"), "Foundation 3.1 Lite");
  assert.equal(compactExtractorVersion("pretrained-foundation-model-v1.5.1-2025-08-07"), "Foundation 1.5.1");
  assert.equal(compactExtractorVersion("pretrained-foundation-model-v1.6-pro-2025-12-01"), "Foundation 1.6 Pro");
  assert.equal(compactExtractorVersion("custom-version-123"), "Version custom-version-123");
  assert.equal(compactExtractorVersion(null), "Version unavailable");
});
