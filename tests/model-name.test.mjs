import assert from "node:assert/strict";
import test from "node:test";

import { modelDisplayName, modelStatusLabel } from "../lib/format.ts";

const models = [
  { id: "qwen/qwen3.6-35b-a3b", name: "Qwen3.6 35B A3B", ready: true, runtime_state: "ready" },
];

test("an installed model shows its readable name", () => {
  assert.equal(modelDisplayName("qwen/qwen3.6-35b-a3b", models), "Qwen3.6 35B A3B");
});

test("a model id the machine does not have is shown as it is", () => {
  // A settings file carried over from another machine names models this one
  // may not have. The id is more use than a blank.
  assert.equal(modelDisplayName("someone/else-7b", models), "someone/else-7b");
});

test("nothing selected says so, rather than showing an empty chip", () => {
  assert.equal(modelDisplayName("", models), "No model selected");
  assert.equal(modelDisplayName("   ", models), "No model selected");
});

test("nothing selected is not reported as a missing model", () => {
  // A fresh install has chosen nothing; that is not the same as having chosen
  // something that cannot be found.
  assert.equal(modelStatusLabel("", undefined), "Choose a model in LLM");
  assert.equal(modelStatusLabel("someone/else-7b", undefined), "Model unavailable");
});

test("an installed model reports its own runtime state", () => {
  assert.equal(modelStatusLabel("qwen/qwen3.6-35b-a3b", models[0]), "Model ready");
});
