import assert from "node:assert/strict";
import test from "node:test";

import {
  distinctDatasets,
  distinctModels,
  distinctPipelines,
  emptyFilters,
  filterEvaluations,
} from "../lib/run-filters.ts";

const evaluation = (overrides) => ({
  id: 1,
  created_at: "2026-08-20T10:00:00+00:00",
  finished_at: null,
  dataset: "invoices",
  model: "qwen/qwen2.5-vl-7b",
  pipeline: "Vision extraction",
  status: "completed",
  total_documents: 5,
  completed_documents: 5,
  error: null,
  max_pages: 1,
  total_elapsed_ms: 5000,
  average_elapsed_ms: 1000,
  metrics: { matched: 8, total: 10, accuracy: 0.8, per_entity: {}, per_confidence: {} },
  ...overrides,
});

test("no filters keeps everything", () => {
  const runs = [evaluation({ id: 1 }), evaluation({ id: 2 })];

  assert.equal(filterEvaluations(runs, emptyFilters).length, 2);
});

test("filtering by model keeps only that model", () => {
  const runs = [evaluation({ id: 1, model: "a" }), evaluation({ id: 2, model: "b" })];

  const filtered = filterEvaluations(runs, { ...emptyFilters, model: "b" });

  assert.deepEqual(filtered.map((run) => run.id), [2]);
});

test("filtering by date keeps runs from that day onwards", () => {
  const runs = [
    evaluation({ id: 1, created_at: "2026-08-18T23:00:00+00:00" }),
    evaluation({ id: 2, created_at: "2026-08-20T01:00:00+00:00" }),
  ];

  const filtered = filterEvaluations(runs, { ...emptyFilters, since: "2026-08-19" });

  assert.deepEqual(filtered.map((run) => run.id), [2]);
});

test("a run created on the boundary day is kept", () => {
  const runs = [evaluation({ id: 1, created_at: "2026-08-19T00:00:01+00:00" })];

  assert.equal(filterEvaluations(runs, { ...emptyFilters, since: "2026-08-19" }).length, 1);
});

test("filtering by accuracy uses a percentage", () => {
  const runs = [
    evaluation({ id: 1, metrics: { matched: 5, total: 10, accuracy: 0.5, per_entity: {}, per_confidence: {} } }),
    evaluation({ id: 2, metrics: { matched: 9, total: 10, accuracy: 0.9, per_entity: {}, per_confidence: {} } }),
  ];

  const filtered = filterEvaluations(runs, { ...emptyFilters, minAccuracy: "80" });

  assert.deepEqual(filtered.map((run) => run.id), [2]);
});

test("a run with no accuracy yet is excluded once a minimum is asked for", () => {
  const runs = [
    evaluation({ id: 1, metrics: { matched: 0, total: 0, accuracy: null, per_entity: {}, per_confidence: {} } }),
  ];

  assert.equal(filterEvaluations(runs, { ...emptyFilters, minAccuracy: "1" }).length, 0);
  assert.equal(filterEvaluations(runs, emptyFilters).length, 1);
});

test("filtering by dataset size uses the document count of the run", () => {
  const runs = [evaluation({ id: 1, total_documents: 3 }), evaluation({ id: 2, total_documents: 20 })];

  const filtered = filterEvaluations(runs, { ...emptyFilters, minDocuments: "10" });

  assert.deepEqual(filtered.map((run) => run.id), [2]);
});

test("filters combine", () => {
  const runs = [
    evaluation({ id: 1, model: "a", total_documents: 20 }),
    evaluation({ id: 2, model: "b", total_documents: 20 }),
    evaluation({ id: 3, model: "b", total_documents: 2 }),
  ];

  const filtered = filterEvaluations(runs, { ...emptyFilters, model: "b", minDocuments: "10" });

  assert.deepEqual(filtered.map((run) => run.id), [2]);
});

test("a non numeric threshold is ignored rather than hiding everything", () => {
  const runs = [evaluation({ id: 1 })];

  assert.equal(filterEvaluations(runs, { ...emptyFilters, minAccuracy: "abc" }).length, 1);
});

test("the model list is deduplicated and sorted", () => {
  const runs = [evaluation({ model: "b" }), evaluation({ model: "a" }), evaluation({ model: "b" })];

  assert.deepEqual(distinctModels(runs), ["a", "b"]);
});

test("runs can be narrowed to one pipeline", () => {
  const runs = [
    evaluation({ id: 1, pipeline: "Vision extraction" }),
    evaluation({ id: 2, pipeline: "OCR then model" }),
  ];

  const filtered = filterEvaluations(runs, { ...emptyFilters, pipeline: "OCR then model" });

  assert.deepEqual(filtered.map((run) => run.id), [2]);
});

test("the pipelines to choose from are the ones that actually ran", () => {
  const runs = [
    evaluation({ pipeline: "Vision extraction" }),
    evaluation({ pipeline: "OCR then model" }),
    evaluation({ pipeline: "Vision extraction" }),
  ];

  assert.deepEqual(distinctPipelines(runs), ["OCR then model", "Vision extraction"]);
});

test("runs can be narrowed to the ones that stayed on this machine", () => {
  const runs = [
    evaluation({ id: 1, provider: "lm_studio", model: "qwen/qwen3.6-35b-a3b" }),
    evaluation({ id: 2, provider: "gemini", model: "gemini-3.7-flash" }),
  ];
  const local = filterEvaluations(runs, { ...emptyFilters, runsOn: "lm_studio" });
  assert.deepEqual(local.map((run) => run.id), [1]);
});

test("runs can be narrowed to the ones that went to an API", () => {
  const runs = [
    evaluation({ id: 1, provider: "lm_studio" }),
    evaluation({ id: 2, provider: "gemini" }),
    evaluation({ id: 3, provider: "gemini" }),
  ];
  const hosted = filterEvaluations(runs, { ...emptyFilters, runsOn: "gemini" });
  assert.deepEqual(hosted.map((run) => run.id), [2, 3]);
});

test("a run whose pipeline called no model has its own filter", () => {
  const runs = [
    evaluation({ id: 1, provider: "lm_studio" }),
    evaluation({ id: 2, provider: "none", model: "Not used" }),
  ];

  const withoutModel = filterEvaluations(runs, { ...emptyFilters, runsOn: "none" });

  assert.deepEqual(withoutModel.map((run) => run.id), [2]);
});

test("no choice shows both, and counts as no active filter", () => {
  const runs = [evaluation({ id: 1, provider: "lm_studio" }), evaluation({ id: 2, provider: "gemini" })];
  assert.equal(filterEvaluations(runs, emptyFilters).length, 2);
  assert.equal(emptyFilters.runsOn, "");
});

test("a run recorded before the provider was stored is treated as local", () => {
  // The backfill writes lm_studio, but a payload from an older backend can
  // still arrive without the field at all.
  const older = evaluation({ id: 9 });
  delete older.provider;
  assert.equal(filterEvaluations([older], { ...emptyFilters, runsOn: "lm_studio" }).length, 1);
  assert.equal(filterEvaluations([older], { ...emptyFilters, runsOn: "gemini" }).length, 0);
});

test("runs can be narrowed to one dataset, because scores across datasets do not compare", () => {
  const runs = [
    evaluation({ id: 1, dataset: "Invoices" }),
    evaluation({ id: 2, dataset: "Receipts" }),
  ];
  const only = filterEvaluations(runs, { ...emptyFilters, dataset: "Invoices" });
  assert.deepEqual(only.map((run) => run.id), [1]);
  assert.equal(filterEvaluations(runs, emptyFilters).length, 2);
});

test("the datasets on offer are the ones that were actually run", () => {
  const runs = [
    evaluation({ dataset: "Receipts" }),
    evaluation({ dataset: "Invoices" }),
    evaluation({ dataset: "Invoices" }),
  ];
  assert.deepEqual(distinctDatasets(runs), ["Invoices", "Receipts"]);
});
