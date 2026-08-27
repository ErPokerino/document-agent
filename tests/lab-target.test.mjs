import assert from "node:assert/strict";
import test from "node:test";

import { labRunTarget } from "../lib/lab-target.ts";

test("the Lab target describes the saved model with its readable name", () => {
  const target = labRunTarget(
    { pipeline: "Vision extraction", model: "google/gemma-4-e4b" },
    { id: "google/gemma-4-e4b", name: "Gemma 4 E4B" },
  );

  assert.deepEqual(target, {
    pipeline: "Vision extraction",
    modelId: "google/gemma-4-e4b",
    modelName: "Gemma 4 E4B",
  });
});

test("a stale model object cannot change the model shown for the next run", () => {
  const target = labRunTarget(
    { pipeline: "Vision extraction", model: "google/gemma-4-e4b" },
    { id: "gemini-3.7-flash", name: "Gemini 3.7 Flash" },
  );

  assert.equal(target.modelId, "google/gemma-4-e4b");
  assert.equal(target.modelName, "google/gemma-4-e4b");
});

test("a pipeline that calls no model names no selected model", () => {
  const target = labRunTarget(
    { pipeline: "Custom Extractor", model: "gemini-3.5-flash-lite" },
    { id: "gemini-3.5-flash-lite", name: "Gemini 3.5 Flash Lite" },
    false,
  );

  assert.equal(target.modelId, "");
  assert.equal(target.modelName, "Not used by this pipeline");
});
