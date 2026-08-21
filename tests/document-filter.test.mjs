import assert from "node:assert/strict";
import test from "node:test";

import { filterByName } from "../lib/document-filter.ts";

const docs = [
  { name: "32363501.pdf" },
  { name: "Invoice-ACME-2026.pdf" },
  { name: "receipt_01.pdf" },
];

test("an empty query keeps everything", () => {
  assert.equal(filterByName(docs, "").length, 3);
  assert.equal(filterByName(docs, "   ").length, 3);
});

test("a substring anywhere in the name matches", () => {
  assert.deepEqual(filterByName(docs, "3635").map((d) => d.name), ["32363501.pdf"]);
});

test("matching ignores case", () => {
  assert.deepEqual(filterByName(docs, "acme").map((d) => d.name), ["Invoice-ACME-2026.pdf"]);
});

test("surrounding whitespace in the query is ignored", () => {
  assert.deepEqual(filterByName(docs, "  receipt  ").map((d) => d.name), ["receipt_01.pdf"]);
});

test("a query that matches nothing returns nothing", () => {
  assert.deepEqual(filterByName(docs, "zzz"), []);
});

test("the original order is preserved", () => {
  assert.deepEqual(filterByName(docs, ".pdf").map((d) => d.name), docs.map((d) => d.name));
});
