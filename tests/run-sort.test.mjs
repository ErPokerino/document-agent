import assert from "node:assert/strict";
import test from "node:test";

import { nextSort, sortEvaluations } from "../lib/run-sort.ts";

const run = (id, overrides = {}) => ({
  id,
  created_at: "2026-08-20T10:00:00+00:00",
  dataset: "Test-Dataset",
  model: "qwen3.5-0.8b",
  status: "completed",
  total_documents: 10,
  total_elapsed_ms: 1000,
  max_pages: 1,
  metrics: { matched: 5, total: 10, accuracy: 0.5, per_entity: {}, per_confidence: {} },
  ...overrides,
});

const ids = (list) => list.map((item) => item.id);

test("sorting by run id descending puts the newest first", () => {
  const runs = [run(1), run(3), run(2)];

  assert.deepEqual(ids(sortEvaluations(runs, "id", "desc")), [3, 2, 1]);
  assert.deepEqual(ids(sortEvaluations(runs, "id", "asc")), [1, 2, 3]);
});

test("sorting by accuracy orders on the number, not on the label", () => {
  const runs = [
    run(1, { metrics: { matched: 8, total: 10, accuracy: 0.8, per_entity: {}, per_confidence: {} } }),
    run(2, { metrics: { matched: 1, total: 10, accuracy: 0.1, per_entity: {}, per_confidence: {} } }),
  ];

  assert.deepEqual(ids(sortEvaluations(runs, "accuracy", "desc")), [1, 2]);
});

test("a run with no accuracy sinks to the bottom in either direction", () => {
  // A failed run has nothing to compare; it must not win the top spot just
  // because its value is missing.
  const runs = [
    run(1, { metrics: { matched: 0, total: 0, accuracy: null, per_entity: {}, per_confidence: {} } }),
    run(2),
  ];

  assert.deepEqual(ids(sortEvaluations(runs, "accuracy", "desc")), [2, 1]);
  assert.deepEqual(ids(sortEvaluations(runs, "accuracy", "asc")), [2, 1]);
});

test("sorting by date uses the timestamp", () => {
  const runs = [
    run(1, { created_at: "2026-08-19T23:00:00+00:00" }),
    run(2, { created_at: "2026-08-21T08:00:00+00:00" }),
  ];

  assert.deepEqual(ids(sortEvaluations(runs, "created_at", "desc")), [2, 1]);
});

test("text columns sort alphabetically and ignore case", () => {
  const runs = [run(1, { model: "qwen3.5-0.8b" }), run(2, { model: "Gemini-3.7" })];

  assert.deepEqual(ids(sortEvaluations(runs, "model", "asc")), [2, 1]);
});

test("numeric columns sort numerically, not as text", () => {
  const runs = [run(1, { total_documents: 9 }), run(2, { total_documents: 10 })];

  assert.deepEqual(ids(sortEvaluations(runs, "total_documents", "asc")), [1, 2]);
});

test("sorting does not mutate the list it was given", () => {
  const runs = [run(2), run(1)];

  sortEvaluations(runs, "id", "asc");

  assert.deepEqual(ids(runs), [2, 1]);
});

test("clicking a new column starts from the most interesting end", () => {
  assert.deepEqual(nextSort(null, "accuracy"), { key: "accuracy", direction: "desc" });
  assert.deepEqual(nextSort({ key: "id", direction: "asc" }, "accuracy"), {
    key: "accuracy",
    direction: "desc",
  });
});

test("clicking the same column again reverses it", () => {
  assert.deepEqual(nextSort({ key: "id", direction: "desc" }, "id"), { key: "id", direction: "asc" });
  assert.deepEqual(nextSort({ key: "id", direction: "asc" }, "id"), { key: "id", direction: "desc" });
});

test("runs sort by what they cost", () => {
  const runs = [run(1), run(2), run(3)];
  const costs = new Map([[1, 0.5], [2, 0.02], [3, 1.4]]);
  const sorted = sortEvaluations(runs, "cost", "asc", (evaluation) => costs.get(evaluation.id));
  assert.deepEqual(ids(sorted), [2, 1, 3]);
  const descending = sortEvaluations(runs, "cost", "desc", (evaluation) => costs.get(evaluation.id));
  assert.deepEqual(ids(descending), [3, 1, 2]);
});

test("a local run has no cost, and does not win the top of the table for it", () => {
  // Cost is null when there is nothing to compute from, which is not zero:
  // a free run and an unpriced one look the same from here.
  const runs = [run(1), run(2)];
  const costs = new Map([[1, null], [2, 0.3]]);
  const sorted = sortEvaluations(runs, "cost", "asc", (evaluation) => costs.get(evaluation.id));
  assert.deepEqual(ids(sorted), [2, 1]);
});

test("sorting by cost without a way to work it out leaves the order alone", () => {
  const runs = [run(1), run(2), run(3)];
  assert.deepEqual(ids(sortEvaluations(runs, "cost", "desc")), [1, 2, 3]);
});
