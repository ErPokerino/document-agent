import assert from "node:assert/strict";
import test from "node:test";

import { buildReviewedExport } from "../lib/review.ts";

const entities = [
  { name: "document_number", format: "text", description: "" },
  { name: "total_amount", format: "decimal", description: "" },
  { name: "page_count", format: "integer", description: "" },
];

const field = (value, confidence = "high", warning = null) => ({ value, confidence, warning });

test("untouched values are exported with the model confidence", () => {
  const exported = buildReviewedExport(
    entities,
    { document_number: field("INV-1"), total_amount: field(10.5), page_count: field(2) },
    { document_number: "INV-1", total_amount: "10.5", page_count: "2" },
    new Set(),
  );

  assert.deepEqual(exported.document_number, {
    value: "INV-1",
    confidence: "high",
    manually_edited: false,
  });
  assert.equal(exported.total_amount.value, 10.5);
  assert.equal(exported.page_count.value, 2);
});

test("an edited value is flagged as manually edited", () => {
  const exported = buildReviewedExport(
    entities,
    { document_number: field("INV-1"), total_amount: field(10.5), page_count: field(2) },
    { document_number: "INV-2", total_amount: "10.5", page_count: "2" },
    new Set(["document_number"]),
  );

  assert.equal(exported.document_number.value, "INV-2");
  assert.equal(exported.document_number.manually_edited, true);
});

test("an emptied value becomes null", () => {
  const exported = buildReviewedExport(
    entities,
    { document_number: field("INV-1"), total_amount: field(10.5), page_count: field(2) },
    { document_number: "   ", total_amount: "10.5", page_count: "2" },
    new Set(["document_number"]),
  );

  assert.equal(exported.document_number.value, null);
});

test("a model warning is kept until the field is corrected", () => {
  const data = {
    document_number: field(null, "low", "Model value was discarded."),
    total_amount: field(10.5),
    page_count: field(2),
  };

  const untouched = buildReviewedExport(entities, data, { total_amount: "10.5", page_count: "2" }, new Set());
  assert.equal(untouched.document_number.warning, "Model value was discarded.");

  const corrected = buildReviewedExport(
    entities,
    data,
    { document_number: "INV-9", total_amount: "10.5", page_count: "2" },
    new Set(["document_number"]),
  );
  assert.equal("warning" in corrected.document_number, false);
});

test("an unparseable decimal keeps what the reviewer typed instead of becoming null", () => {
  // JSON.stringify turns NaN into null, which silently discarded the input.
  const exported = buildReviewedExport(
    entities,
    { document_number: field("INV-1"), total_amount: field(10.5), page_count: field(2) },
    { document_number: "INV-1", total_amount: "1.234,56", page_count: "2" },
    new Set(["total_amount"]),
  );

  assert.equal(exported.total_amount.value, "1.234,56");
  assert.notEqual(JSON.parse(JSON.stringify(exported)).total_amount.value, null);
});

test("a decimal typed into an integer field is not silently truncated", () => {
  const exported = buildReviewedExport(
    entities,
    { document_number: field("INV-1"), total_amount: field(10.5), page_count: field(2) },
    { document_number: "INV-1", total_amount: "10.5", page_count: "12.7" },
    new Set(["page_count"]),
  );

  assert.equal(exported.page_count.value, "12.7");
});

test("an entity added after the extraction does not crash the export", () => {
  const withExtra = [...entities, { name: "brand_new", format: "text", description: "" }];

  const exported = buildReviewedExport(
    withExtra,
    { document_number: field("INV-1"), total_amount: field(10.5), page_count: field(2) },
    { document_number: "INV-1", total_amount: "10.5", page_count: "2" },
    new Set(),
  );

  assert.equal(exported.brand_new.value, null);
  assert.equal(exported.brand_new.confidence, "low");
});
