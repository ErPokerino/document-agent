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
