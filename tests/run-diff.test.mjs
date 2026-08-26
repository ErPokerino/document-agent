import assert from "node:assert/strict";
import test from "node:test";

import { diffRuns } from "../lib/run-diff.ts";

const field = (entity, expected, actual, matched, confidence = "high") => ({
  entity, expected, actual, matched, confidence,
});

const doc = (name, items, overrides = {}) => ({
  name, status: "ok", error: null, elapsed_ms: 1000,
  prompt_tokens: 100, completion_tokens: 10, items, ...overrides,
});

const run = (id, documents) => ({
  id, dataset: "Test-Dataset", model: "m", pipeline: "p", status: "completed",
  documents,
});

test("a field that went from wrong to right is a fix", () => {
  const diff = diffRuns(
    run(1, [doc("a.pdf", [field("date", "2026-01-01", "2020-01-01", false)])]),
    run(2, [doc("a.pdf", [field("date", "2026-01-01", "2026-01-01", true)])]),
  );
  assert.equal(diff.summary.fixed, 1);
  assert.equal(diff.summary.broken, 0);
  assert.equal(diff.fixed[0].entity, "date");
  assert.equal(diff.fixed[0].document, "a.pdf");
});

test("a field that went from right to wrong is a regression", () => {
  const diff = diffRuns(
    run(1, [doc("a.pdf", [field("date", "2026-01-01", "2026-01-01", true)])]),
    run(2, [doc("a.pdf", [field("date", "2026-01-01", null, false)])]),
  );
  assert.equal(diff.summary.broken, 1);
  assert.equal(diff.broken[0].before.value, "2026-01-01");
  assert.equal(diff.broken[0].after.value, null);
});

test("wrong both times but differently is neither a fix nor a regression", () => {
  // Worth seeing — the answer moved — without being counted as progress.
  const diff = diffRuns(
    run(1, [doc("a.pdf", [field("name", "ACME", "ACNE", false)])]),
    run(2, [doc("a.pdf", [field("name", "ACME", "ACMÉ", false)])]),
  );
  assert.equal(diff.summary.fixed, 0);
  assert.equal(diff.summary.broken, 0);
  assert.equal(diff.summary.changed, 1);
});

test("an identical answer is counted and not listed", () => {
  const diff = diffRuns(
    run(1, [doc("a.pdf", [field("date", "x", "x", true)])]),
    run(2, [doc("a.pdf", [field("date", "x", "x", true)])]),
  );
  assert.equal(diff.summary.unchanged, 1);
  assert.equal(diff.fixed.length + diff.broken.length + diff.changed.length, 0);
});

test("a net score says which way the run moved overall", () => {
  const diff = diffRuns(
    run(1, [doc("a.pdf", [
      field("one", "x", "y", false),
      field("two", "x", "x", true),
      field("three", "x", "x", true),
    ])]),
    run(2, [doc("a.pdf", [
      field("one", "x", "x", true),
      field("two", "x", "y", false),
      field("three", "x", "x", true),
    ])]),
  );
  assert.equal(diff.summary.fixed, 1);
  assert.equal(diff.summary.broken, 1);
  // One each way: aggregates would have shown no change at all.
  assert.equal(diff.summary.net, 0);
});

test("a document only one run reached is reported, not silently dropped", () => {
  const diff = diffRuns(
    run(1, [doc("a.pdf", [field("d", "x", "x", true)]), doc("b.pdf", [field("d", "x", "x", true)])]),
    run(2, [doc("a.pdf", [field("d", "x", "x", true)])]),
  );
  assert.deepEqual(diff.onlyInBefore, ["b.pdf"]);
  assert.deepEqual(diff.onlyInAfter, []);
});

test("a field only one run scored is reported as appearing or disappearing", () => {
  const diff = diffRuns(
    run(1, [doc("a.pdf", [field("d", "x", "x", true)])]),
    run(2, [doc("a.pdf", [field("d", "x", "x", true), field("extra", "y", "y", true)])]),
  );
  assert.equal(diff.summary.added, 1);
  assert.equal(diff.added[0].entity, "extra");
});

test("a document that failed on one side is not read as every field regressing", () => {
  // A crashed document has no items. Counting them as broken would drown the
  // fields that genuinely changed.
  const diff = diffRuns(
    run(1, [doc("a.pdf", [field("d", "x", "x", true)])]),
    run(2, [doc("a.pdf", [], { status: "failed", error: "model gone", elapsed_ms: null })]),
  );
  assert.equal(diff.summary.broken, 0);
  assert.deepEqual(diff.failedAfter, ["a.pdf"]);
});

test("the fields that moved come back grouped by document, worst first", () => {
  const diff = diffRuns(
    run(1, [
      doc("clean.pdf", [field("d", "x", "x", true)]),
      doc("messy.pdf", [field("a", "x", "y", false), field("b", "x", "x", true)]),
    ]),
    run(2, [
      doc("clean.pdf", [field("d", "x", "x", true)]),
      doc("messy.pdf", [field("a", "x", "x", true), field("b", "x", "z", false)]),
    ]),
  );
  assert.deepEqual(diff.byDocument.map((entry) => entry.document), ["messy.pdf"]);
  assert.equal(diff.byDocument[0].changes.length, 2);
});

test("two runs with nothing in common do not pretend to compare", () => {
  const diff = diffRuns(run(1, []), run(2, []));
  assert.equal(diff.summary.unchanged, 0);
  assert.equal(diff.byDocument.length, 0);
});
