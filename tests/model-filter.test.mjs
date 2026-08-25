import assert from "node:assert/strict";
import test from "node:test";

import { filterModels, sizeBuckets } from "../lib/model-filter.ts";

const model = (id, overrides = {}) => ({
  id,
  name: id,
  provider: "lm_studio",
  vision: true,
  size_bytes: 2 * 1024 ** 3,
  ...overrides,
});

const all = [
  model("small-vision", { size_bytes: 1 * 1024 ** 3 }),
  model("big-text", { vision: false, size_bytes: 20 * 1024 ** 3 }),
  model("hosted", { provider: "gemini", size_bytes: null }),
];

const ids = (list) => list.map((item) => item.id);

test("no filters leaves the list as it is", () => {
  assert.deepEqual(ids(filterModels(all, {})), ["small-vision", "big-text", "hosted"]);
});

test("filtering by where the model runs", () => {
  assert.deepEqual(ids(filterModels(all, { runs: "local" })), ["small-vision", "big-text"]);
  assert.deepEqual(ids(filterModels(all, { runs: "api" })), ["hosted"]);
});

test("filtering by whether the model can read a page image", () => {
  assert.deepEqual(ids(filterModels(all, { vision: "vision" })), ["small-vision", "hosted"]);
  assert.deepEqual(ids(filterModels(all, { vision: "text" })), ["big-text"]);
});

test("filtering by how much disk the model takes", () => {
  assert.deepEqual(ids(filterModels(all, { size: "small" })), ["small-vision"]);
  assert.deepEqual(ids(filterModels(all, { size: "large" })), ["big-text"]);
});

test("a model with no size on disk is not claimed by any size bucket", () => {
  // A hosted model has no file here; hiding it under "small" would be a lie.
  const sizes = sizeBuckets.map((bucket) => bucket.value).filter((value) => value !== "any");

  for (const size of sizes) {
    assert.equal(ids(filterModels([model("hosted", { provider: "gemini", size_bytes: null })], { size })).length, 0);
  }
});

test("filters combine", () => {
  assert.deepEqual(ids(filterModels(all, { runs: "local", vision: "vision" })), ["small-vision"]);
  assert.deepEqual(ids(filterModels(all, { runs: "local", vision: "vision", size: "large" })), []);
});

test("a model whose capabilities are unknown claims neither of them", () => {
  // The OpenAI-compatible endpoint reports ids alone. Calling such a model
  // text-only would hide it from every vision pipeline on the strength of an
  // answer nobody gave.
  const unknown = { id: "mystery", name: "Mystery", provider: "lm_studio", vision: false, capabilities_known: false, size_bytes: null };
  assert.equal(filterModels([unknown], { vision: "any" }).length, 1);
  assert.equal(filterModels([unknown], { vision: "vision" }).length, 0);
  assert.equal(filterModels([unknown], { vision: "text" }).length, 0);
});

test("a model that did report its capabilities still filters both ways", () => {
  const seeing = { id: "a", name: "A", provider: "lm_studio", vision: true, capabilities_known: true };
  const reading = { id: "b", name: "B", provider: "lm_studio", vision: false, capabilities_known: true };
  assert.deepEqual(filterModels([seeing, reading], { vision: "vision" }).map((m) => m.id), ["a"]);
  assert.deepEqual(filterModels([seeing, reading], { vision: "text" }).map((m) => m.id), ["b"]);
});
