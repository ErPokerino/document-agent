import assert from "node:assert/strict";
import test from "node:test";

import {
  METRICS,
  buildPivot,
  cellKey,
  entityBreakdown,
} from "../lib/run-pivot.ts";

const run = (overrides) => ({
  id: 1,
  dataset: "Test-Dataset",
  model: "qwen/qwen3.6-35b-a3b",
  pipeline: "Vision extraction",
  provider: "lm_studio",
  status: "completed",
  total_documents: 10,
  succeeded_documents: 10,
  total_elapsed_ms: 1_938_000,
  average_elapsed_ms: 193_800,
  prompt_tokens: 4000,
  completion_tokens: 400,
  ocr_pages: 0,
  layout_pages: 0,
  metrics: { matched: 57, total: 60, accuracy: 0.95, per_entity: {}, per_confidence: {} },
  ...overrides,
});

const noCost = () => null;

test("the matrix is models against pipelines", () => {
  const pivot = buildPivot(
    [
      run({ id: 1, model: "A", pipeline: "Vision" }),
      run({ id: 2, model: "A", pipeline: "OCR" }),
      run({ id: 3, model: "B", pipeline: "Vision" }),
    ],
    "accuracy",
    noCost,
  );
  assert.deepEqual(pivot.rows, ["A", "B"]);
  assert.deepEqual(pivot.columns, ["OCR", "Vision"]);
  // B was never run through OCR, and an empty cell is not a zero.
  assert.equal(pivot.cells.get(cellKey("B", "OCR")), undefined);
});

test("repeat runs of one approach are averaged, and the count is kept", () => {
  const pivot = buildPivot(
    [
      run({ id: 1, metrics: { matched: 6, total: 10, accuracy: 0.6, per_entity: {}, per_confidence: {} } }),
      run({ id: 2, metrics: { matched: 8, total: 10, accuracy: 0.8, per_entity: {}, per_confidence: {} } }),
    ],
    "accuracy",
    noCost,
  );
  const cell = pivot.cells.get(cellKey("qwen/qwen3.6-35b-a3b", "Vision extraction"));
  assert.ok(Math.abs(cell.value - 0.7) < 1e-9);
  // Two runs behind one number is worth knowing before trusting it.
  assert.equal(cell.runs, 2);
});

test("a run that scored nothing does not drag an average down to zero", () => {
  const pivot = buildPivot(
    [
      run({ id: 1, metrics: { matched: 9, total: 10, accuracy: 0.9, per_entity: {}, per_confidence: {} } }),
      run({ id: 2, metrics: { matched: 0, total: 0, accuracy: null, per_entity: {}, per_confidence: {} } }),
    ],
    "accuracy",
    noCost,
  );
  const cell = pivot.cells.get(cellKey("qwen/qwen3.6-35b-a3b", "Vision extraction"));
  assert.equal(cell.value, 0.9);
  assert.equal(cell.runs, 1);
});

test("time is per document, so runs over different dataset sizes compare", () => {
  const pivot = buildPivot([run({ average_elapsed_ms: 193_800 })], "seconds_per_document", noCost);
  const cell = pivot.cells.get(cellKey("qwen/qwen3.6-35b-a3b", "Vision extraction"));
  assert.ok(Math.abs(cell.value - 193.8) < 1e-9);
});

test("cost is per document too, and comes from the caller", () => {
  const pivot = buildPivot([run({ succeeded_documents: 10 })], "cost_per_document", () => 0.1);
  const cell = pivot.cells.get(cellKey("qwen/qwen3.6-35b-a3b", "Vision extraction"));
  assert.ok(Math.abs(cell.value - 0.01) < 1e-9);
});

test("the winner depends on which way the metric is good", () => {
  const runs = [
    run({ id: 1, model: "A", average_elapsed_ms: 10_000, metrics: { matched: 9, total: 10, accuracy: 0.9, per_entity: {}, per_confidence: {} } }),
    run({ id: 2, model: "B", average_elapsed_ms: 90_000, metrics: { matched: 10, total: 10, accuracy: 1.0, per_entity: {}, per_confidence: {} } }),
  ];
  assert.equal(buildPivot(runs, "accuracy", noCost).best.row, "B");
  // Fastest wins when the metric is time, not the largest number.
  assert.equal(buildPivot(runs, "seconds_per_document", noCost).best.row, "A");
});

test("every metric says which direction is better", () => {
  for (const metric of METRICS) {
    assert.ok(metric.key && metric.label);
    assert.ok(metric.higherIsBetter === true || metric.higherIsBetter === false);
  }
});

test("nothing to compare produces an empty matrix, not a crash", () => {
  const pivot = buildPivot([], "accuracy", noCost);
  assert.deepEqual(pivot.rows, []);
  assert.deepEqual(pivot.columns, []);
  assert.equal(pivot.best, null);
});

test("the entity breakdown shows where an approach loses, not just that it did", () => {
  const runs = [
    run({
      id: 1,
      model: "A",
      metrics: {
        matched: 17, total: 20, accuracy: 0.85,
        per_entity: {
          supplier_name: { matched: 8, total: 10 },
          date: { matched: 9, total: 10 },
        },
        per_confidence: {},
      },
    }),
    run({
      id: 2,
      model: "B",
      metrics: {
        matched: 20, total: 20, accuracy: 1,
        per_entity: {
          supplier_name: { matched: 10, total: 10 },
          date: { matched: 10, total: 10 },
        },
        per_confidence: {},
      },
    }),
  ];
  const breakdown = entityBreakdown(runs);
  assert.deepEqual(breakdown.entities, ["date", "supplier_name"]);
  assert.deepEqual(breakdown.approaches.map((a) => a.model), ["A", "B"]);
  const a = breakdown.approaches[0];
  assert.ok(Math.abs(a.byEntity.get("supplier_name") - 0.8) < 1e-9);
  assert.equal(breakdown.approaches[1].byEntity.get("supplier_name"), 1);
});

test("an entity no run scored is left out of the breakdown", () => {
  const breakdown = entityBreakdown([run({ metrics: { matched: 0, total: 0, accuracy: null, per_entity: { ghost: { matched: 0, total: 0 } }, per_confidence: {} } })]);
  assert.deepEqual(breakdown.entities, []);
});
