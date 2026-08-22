import assert from "node:assert/strict";
import test from "node:test";

import { runsToCsv } from "../lib/runs-csv.ts";

const run = (overrides = {}) => ({
  id: 16,
  created_at: "2026-08-22T20:20:00+00:00",
  finished_at: "2026-08-22T20:21:00+00:00",
  dataset: "Test-Dataset",
  model: "gemini-3.5-flash-lite",
  pipeline: "OCR then model",
  status: "completed",
  total_documents: 10,
  completed_documents: 10,
  succeeded_documents: 10,
  failed_documents: 0,
  pending_documents: 0,
  error: null,
  max_pages: 1,
  total_elapsed_ms: 49400,
  average_elapsed_ms: 4940,
  prompt_tokens: 11312,
  completion_tokens: 1339,
  ocr_pages: 10,
  layout_pages: 0,
  metrics: { matched: 49, total: 50, accuracy: 0.98, per_entity: {}, per_confidence: {} },
  ...overrides,
});

const rows = (csv) => csv.trim().split("\n").map((line) => line.split(","));

test("one row per run, with the columns an analysis needs", () => {
  const [header, first] = rows(runsToCsv([run()], null));

  assert.deepEqual(header.slice(0, 6), ["run_id", "created_at", "dataset", "pipeline", "model", "status"]);
  assert.equal(first[0], "16");
  assert.equal(first[3], "OCR then model");
  assert.equal(header.length, first.length);
});

test("accuracy is a number a spreadsheet can use, not a percentage string", () => {
  const [header, first] = rows(runsToCsv([run()], null));

  assert.equal(first[header.indexOf("accuracy")], "0.98");
  assert.equal(first[header.indexOf("matched")], "49");
  assert.equal(first[header.indexOf("scored_fields")], "50");
});

test("a run that scored nothing leaves accuracy empty rather than zero", () => {
  const empty = run({ metrics: { matched: 0, total: 0, accuracy: null, per_entity: {}, per_confidence: {} } });
  const [header, first] = rows(runsToCsv([empty], null));

  assert.equal(first[header.indexOf("accuracy")], "");
});

test("cost is only stated when there is a rate to state it from", () => {
  const priced = runsToCsv([run()], {
    pricing: { "gemini-3.5-flash-lite": { input_per_million: 0.3, output_per_million: 2.5 } },
    gcp: { ocr_per_thousand_pages: 1.5, layout_per_thousand_pages: 10 },
  });
  const unpriced = runsToCsv([run()], null);
  const column = rows(priced)[0].indexOf("cost_usd");

  assert.notEqual(rows(priced)[1][column], "");
  assert.equal(rows(unpriced)[1][column], "");
});

test("a value holding a comma or a quote survives the round trip", () => {
  const awkward = run({ dataset: 'Fatture, "2026"' });

  const line = runsToCsv([awkward], null).trim().split("\n")[1];

  assert.match(line, /"Fatture, ""2026"""/);
});

test("the rows come out in the order they were given", () => {
  const csv = runsToCsv([run({ id: 3 }), run({ id: 1 }), run({ id: 2 })], null);

  assert.deepEqual(rows(csv).slice(1).map((row) => row[0]), ["3", "1", "2"]);
});

test("an empty selection still produces a header", () => {
  assert.equal(runsToCsv([], null).trim().split("\n").length, 1);
});
