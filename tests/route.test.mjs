import assert from "node:assert/strict";
import test from "node:test";

import { formatHash, parseHash } from "../lib/route.ts";

test("an empty hash is the workspace", () => {
  const route = parseHash("");
  assert.equal(route.view, "workspace");
  assert.equal(route.evaluationId, null);
  assert.equal(formatHash(route), "#/workspace");
});

test("a lab run and its filters survive a round trip", () => {
  const route = parseHash("#/lab/42?dataset=Invoices&minAccuracy=0.8");
  assert.equal(route.view, "lab");
  assert.equal(route.evaluationId, 42);
  assert.deepEqual(route.filters.dataset, ["Invoices"]);
  assert.equal(route.filters.minAccuracy, "0.8");
  assert.equal(parseHash(formatHash(route)).evaluationId, 42);
  assert.deepEqual(parseHash(formatHash(route)).filters.dataset, ["Invoices"]);
});

test("a dataset name with a space round trips", () => {
  const route = parseHash("#/datasets/Q1%20invoices");
  assert.equal(route.dataset, "Q1 invoices");
  assert.equal(formatHash(route), "#/datasets/Q1%20invoices");
});

test("an unknown section is the workspace", () => {
  assert.equal(parseHash("#/nope").view, "workspace");
});
