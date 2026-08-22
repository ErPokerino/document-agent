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
