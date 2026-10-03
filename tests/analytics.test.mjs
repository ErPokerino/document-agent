import assert from "node:assert/strict";
import test from "node:test";

import {
  AXES,
  approachPoints,
  fieldAccuracy,
  paretoFrontier,
} from "../lib/analytics.ts";

const run = (overrides) => ({
  id: 1,
  dataset: "Test-Dataset",
  model: "M",
  pipeline: "P",
  provider: "lm_studio",
  status: "completed",
  total_documents: 10,
  succeeded_documents: 10,
  total_elapsed_ms: 100_000,
  average_elapsed_ms: 10_000,
  prompt_tokens: 1000,
  completion_tokens: 100,
  ocr_pages: 0,
  layout_pages: 0,
  metrics: { matched: 9, total: 10, accuracy: 0.9, per_entity: {}, per_confidence: {} },
  ...overrides,
});

const free = () => null;

// -- one point per approach ---------------------------------------------------

test("runs that share a fingerprint are one approach", () => {
  const points = approachPoints(
    [
      run({ fingerprint: "abc", pipeline: "Vision" }),
      run({ id: 2, fingerprint: "abc", pipeline: "Renamed" }),
      run({ id: 3, fingerprint: "def", pipeline: "Vision" }),
    ],
    free,
  );
  assert.equal(points.length, 2);
  assert.equal(points.find((point) => point.key === "abc").runs, 2);
});

test("each model and pipeline pair becomes one point", () => {
  const points = approachPoints(
    [run({ model: "A", pipeline: "Vision" }), run({ model: "A", pipeline: "OCR" })],
    free,
  );
  assert.equal(points.length, 2);
  assert.deepEqual(points.map((p) => p.pipeline).sort(), ["OCR", "Vision"]);
});

test("repeat runs of one approach average into its point", () => {
  const points = approachPoints(
    [
      run({ id: 1, metrics: { matched: 8, total: 10, accuracy: 0.8, per_entity: {}, per_confidence: {} } }),
      run({ id: 2, metrics: { matched: 10, total: 10, accuracy: 1, per_entity: {}, per_confidence: {} } }),
    ],
    free,
  );
  assert.equal(points.length, 1);
  assert.ok(Math.abs(points[0].accuracy - 0.9) < 1e-9);
  assert.equal(points[0].runs, 2);
});

test("an approach that never scored is not a point at zero accuracy", () => {
  const points = approachPoints(
    [run({ metrics: { matched: 0, total: 0, accuracy: null, per_entity: {}, per_confidence: {} } })],
    free,
  );
  assert.deepEqual(points, []);
});

test("time and cost are per document so approaches compare across dataset sizes", () => {
  const points = approachPoints([run({ average_elapsed_ms: 10_000, succeeded_documents: 10 })], () => 0.5);
  assert.ok(Math.abs(points[0].secondsPerDocument - 10) < 1e-9);
  assert.ok(Math.abs(points[0].costPerDocument - 0.05) < 1e-9);
});

// -- the frontier -------------------------------------------------------------

const point = (model, accuracy, seconds) => ({
  key: model,
  model,
  pipeline: "P",
  runs: 1,
  accuracy,
  secondsPerDocument: seconds,
  costPerDocument: seconds,
  tokensPerDocument: null,
});

test("a point beaten on both axes is not on the frontier", () => {
  const points = [
    point("fast-and-good", 0.95, 5),
    point("slow-and-worse", 0.80, 50),
  ];
  const frontier = paretoFrontier(points, "secondsPerDocument");
  assert.deepEqual(frontier.map((p) => p.model), ["fast-and-good"]);
});

test("a trade-off keeps both, because neither is beaten outright", () => {
  const points = [
    point("cheapest", 0.80, 2),
    point("best", 0.98, 60),
  ];
  const frontier = paretoFrontier(points, "secondsPerDocument");
  assert.deepEqual(frontier.map((p) => p.model).sort(), ["best", "cheapest"]);
});

test("the frontier comes out in drawing order, left to right", () => {
  const points = [point("c", 0.99, 90), point("a", 0.70, 3), point("b", 0.90, 20)];
  const frontier = paretoFrontier(points, "secondsPerDocument");
  assert.deepEqual(frontier.map((p) => p.secondsPerDocument), [3, 20, 90]);
});

test("an equal point does not knock out the one it ties with", () => {
  const points = [point("a", 0.9, 10), point("b", 0.9, 10)];
  assert.equal(paretoFrontier(points, "secondsPerDocument").length, 2);
});

test("a point with nothing on the chosen axis cannot be placed", () => {
  const points = [point("a", 0.9, null), point("b", 0.8, 5)];
  const frontier = paretoFrontier(points, "secondsPerDocument");
  assert.deepEqual(frontier.map((p) => p.model), ["b"]);
});

test("nothing in, nothing out", () => {
  assert.deepEqual(paretoFrontier([], "costPerDocument"), []);
});

// -- accuracy per field -------------------------------------------------------

test("fields are scored over every run in view, not per run", () => {
  const runs = [
    run({
      id: 1,
      metrics: {
        matched: 1, total: 2, accuracy: 0.5,
        per_entity: { supplier_name: { matched: 1, total: 2 } },
        per_confidence: {},
      },
    }),
    run({
      id: 2,
      metrics: {
        matched: 2, total: 2, accuracy: 1,
        per_entity: { supplier_name: { matched: 2, total: 2 } },
        per_confidence: {},
      },
    }),
  ];
  const fields = fieldAccuracy(runs);
  assert.equal(fields.length, 1);
  assert.equal(fields[0].entity, "supplier_name");
  assert.equal(fields[0].matched, 3);
  assert.equal(fields[0].total, 4);
  assert.equal(fields[0].accuracy, 0.75);
});

test("the worst field comes first, because that is the one to act on", () => {
  const runs = [
    run({
      metrics: {
        matched: 0, total: 0, accuracy: null,
        per_entity: {
          date: { matched: 10, total: 10 },
          supplier_name: { matched: 3, total: 10 },
          currency: { matched: 8, total: 10 },
        },
        per_confidence: {},
      },
    }),
  ];
  assert.deepEqual(fieldAccuracy(runs).map((f) => f.entity), ["supplier_name", "currency", "date"]);
});

test("a field nothing was scored against is left out", () => {
  const runs = [run({ metrics: { matched: 0, total: 0, accuracy: null, per_entity: { ghost: { matched: 0, total: 0 } }, per_confidence: {} } })];
  assert.deepEqual(fieldAccuracy(runs), []);
});

test("a zero on an axis reads as zero, not as a rounded fraction of one", () => {
  // The left-hand tick is always zero, and "$0.0" or "0.0 s" there looks like
  // a number that was measured rather than the origin of the axis.
  for (const axis of AXES) {
    assert.equal(axis.format(0), axis.key === "costPerDocument" ? "$0" : "0");
  }
});

test("each axis still formats a real value in its own units", () => {
  const by = Object.fromEntries(AXES.map((axis) => [axis.key, axis]));
  assert.equal(by.secondsPerDocument.format(4.7), "4.7 s");
  assert.equal(by.secondsPerDocument.format(214), "214 s");
  assert.match(by.costPerDocument.format(0.0022), /^\$0\.0022$/);
  assert.equal(by.tokensPerDocument.format(1288), (1288).toLocaleString());
});

test("different recorded OCR versions remain distinct approaches", () => {
  const bindings = (version) => [{kind: "document_ai_ocr", config: {project_id: "project", location: "eu", processor_id: `processor/processorVersions/${version}`}}];
  const points = approachPoints([run({processor_bindings: bindings("v1")}), run({id: 2, processor_bindings: bindings("v2")}), run({id: 3, processor_bindings: bindings("v1")})], free);
  assert.equal(points.length, 2);
  assert.deepEqual(points.map(p => p.runs).sort(), [1, 2]);
  assert.ok(points.every(p => p.detail.includes("OCR:")));
});

test("a run that reused stored readings counts for accuracy but not for time or cost", () => {
  const [point] = approachPoints(
    [
      run({ fingerprint: "abc", average_elapsed_ms: 10_000 }),
      run({ id: 2, fingerprint: "abc", average_elapsed_ms: 1_000, cached_pages: 10, reuse_readings: true }),
    ],
    () => 1,
  );

  assert.equal(point.runs, 2);
  assert.equal(point.secondsPerDocument, 10);
  assert.equal(point.costPerDocument, 0.1);
});
