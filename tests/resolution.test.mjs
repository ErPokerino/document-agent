import assert from "node:assert/strict";
import test from "node:test";

import { describeRule, moveInList, priorityWithAll, resolutionOf, upstreamMethods } from "../lib/resolution.ts";

const steps = [
  { kind: "read_pdf_text", config: {} },
  { kind: "llm_extract", config: {} },
  { kind: "artifact_predict", config: { artifact_id: "abc" } },
  { kind: "regex_refine", config: {} },
  { kind: "regex_refine", config: {} },
  { kind: "resolve_candidates", config: {} },
];

test("methods are named as the backend names them, readers and resolvers left out", () => {
  assert.deepEqual(upstreamMethods(steps, 5, [{ id: "abc", name: "suppliers" }]), [
    "llm_extract",
    "trained: suppliers",
    "regex_refine #1",
    "regex_refine #2",
  ]);
});

test("only the steps before the resolver are its methods", () => {
  assert.deepEqual(upstreamMethods(steps, 2, []), ["llm_extract"]);
});

test("a saved priority keeps its order and gains the methods it does not list", () => {
  assert.deepEqual(priorityWithAll(["trained: x", "gone"], ["llm_extract", "trained: x"]), ["trained: x", "llm_extract"]);
});

test("moving past either end changes nothing", () => {
  assert.deepEqual(moveInList(["a", "b"], 0, -1), ["a", "b"]);
  assert.deepEqual(moveInList(["a", "b"], 0, 1), ["b", "a"]);
});

test("a step saved without a config resolves as before candidates existed", () => {
  assert.equal(resolutionOf({}).default.strategy, "last");
});

test("a priority rule reads as its order", () => {
  assert.equal(describeRule({ strategy: "priority", priority: ["a", "b"], minimum_score: null }), "Priority: a → b");
});
