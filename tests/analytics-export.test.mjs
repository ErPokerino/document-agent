import assert from "node:assert/strict";
import test from "node:test";

import { approachesToCsv, fieldChartSvg, fieldsToCsv } from "../lib/analytics-export.ts";

const point = (overrides) => ({
  key: "a",
  model: "M",
  pipeline: "P",
  dataset: "D",
  detail: "reader",
  runs: 2,
  accuracy: 0.9,
  secondsPerDocument: 1.5,
  costPerDocument: null,
  tokensPerDocument: 100,
  ...overrides,
});

test("the approach csv uses the chart rank and leaves a missing cost empty", () => {
  const points = [point({ key: "a", model: "Alpha" }), point({ key: "b", model: "Beta, inc", accuracy: 0.5, costPerDocument: 0.01 })];
  const csv = approachesToCsv(points, [points[0]], "secondsPerDocument");
  const [header, first, second] = csv.trim().split("\n");

  assert.equal(header.split(",")[0], "rank");
  assert.equal(first.split(",")[0], "1");
  assert.equal(first.includes("yes"), true);
  assert.equal(first.split(",")[8], "");
  assert.match(second, /"Beta, inc"/);
  assert.match(second, /Seconds per document,no/);
});

test("field csv keeps the pooled counts as numbers", () => {
  const csv = fieldsToCsv([{ entity: "total_amount", matched: 8, total: 10, accuracy: 0.8 }]);
  assert.equal(csv, "entity,matched,total,accuracy\ntotal_amount,8,10,0.8\n");
});

test("the field picture names each field and sizes the bar from its accuracy", () => {
  const svg = fieldChartSvg(
    [{ entity: "currency", matched: 9, total: 10, accuracy: 0.9 }],
    { paper: "#fff", ink: "#111", muted: "#666", track: "#eee" },
  );
  assert.match(svg, /currency/);
  assert.match(svg, /width="378"/);
  assert.match(svg, /90%/);
});
