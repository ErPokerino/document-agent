import assert from "node:assert/strict";
import test from "node:test";

import { documentAiCost, estimateCost, formatUsd, totalCost } from "../lib/cost.ts";

const rate = { input_per_million: 0.3, output_per_million: 2.5 };

test("cost is the two rates applied to the two token counts", () => {
  // 1M input at $0.30 plus 1M output at $2.50.
  assert.equal(estimateCost(1_000_000, 1_000_000, rate), 2.8);
});

test("a realistic single document costs a fraction of a cent", () => {
  const cost = estimateCost(1300, 100, rate);

  assert.ok(cost > 0 && cost < 0.001, `expected a sub-cent cost, got ${cost}`);
});

test("no rate configured means no number, not a zero", () => {
  // A missing price must never be reported as free.
  assert.equal(estimateCost(1300, 100, undefined), null);
  assert.equal(estimateCost(1300, 100, { input_per_million: null, output_per_million: 2.5 }), null);
  assert.equal(estimateCost(1300, 100, { input_per_million: 0.3, output_per_million: null }), null);
});

test("no token counts means no number either", () => {
  // A local run records nothing, and $0.00 would read as "this was free".
  assert.equal(estimateCost(0, 0, rate), null);
});

test("output-only usage still costs something", () => {
  assert.ok((estimateCost(0, 1000, rate) ?? 0) > 0);
});

test("small amounts keep enough decimals to be readable", () => {
  // Two significant figures. Asserting the rounding of a value sitting exactly
  // between two doubles would test the float representation, not the format.
  assert.equal(formatUsd(0.0064), "$0.0064");
  assert.equal(formatUsd(0.00012), "$0.00012");
  assert.notEqual(formatUsd(0.0064), "$0.01");
});

test("larger amounts read as ordinary money", () => {
  assert.equal(formatUsd(12.3456), "$12.35");
  assert.equal(formatUsd(1), "$1.00");
});

test("no value formats as a dash, never as zero", () => {
  assert.equal(formatUsd(null), "—");
});

test("pages sent to Document AI are priced per thousand", () => {
  const gcp = { ocr_per_thousand_pages: 1.5, layout_per_thousand_pages: 10 };

  assert.equal(documentAiCost(1000, 0, gcp), 1.5);
  assert.equal(documentAiCost(0, 100, gcp), 1);
  assert.equal(documentAiCost(10, 10, gcp), 0.015 + 0.1);
});

test("a run that touched no processor costs nothing to say", () => {
  assert.equal(documentAiCost(0, 0, { ocr_per_thousand_pages: 1.5, layout_per_thousand_pages: 10 }), null);
});

test("a missing rate is not the same as free", () => {
  assert.equal(documentAiCost(10, 0, { ocr_per_thousand_pages: null, layout_per_thousand_pages: 10 }), null);
  assert.equal(documentAiCost(10, 0, null), null);
});

test("the total adds what the model cost to what the pages cost", () => {
  const pricing = { input_per_million: 1, output_per_million: 2 };
  const gcp = { ocr_per_thousand_pages: 1.5, layout_per_thousand_pages: 10 };

  assert.equal(totalCost({ promptTokens: 1_000_000, completionTokens: 0, ocrPages: 1000, layoutPages: 0 }, pricing, gcp), 2.5);
  // Only one of the two known: the total is still what is known, not null.
  assert.equal(totalCost({ promptTokens: 0, completionTokens: 0, ocrPages: 1000, layoutPages: 0 }, null, gcp), 1.5);
  assert.equal(totalCost({ promptTokens: 0, completionTokens: 0, ocrPages: 0, layoutPages: 0 }, pricing, gcp), null);
});
