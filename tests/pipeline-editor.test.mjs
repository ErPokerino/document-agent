import assert from "node:assert/strict";
import test from "node:test";

import {
  addStep,
  defaultConfigFor,
  emptyRule,
  moveStep,
  removeStep,
  rulesOf,
  pageLimitProblem,
  setStepConfig,
  stepLabels,
  summarizeStep,
} from "../lib/pipeline-editor.ts";

const steps = () => [
  { kind: "render_pages", config: { scale: 1.35 } },
  { kind: "llm_extract", config: {} },
];

test("a step moves up and down, and stays put at the ends", () => {
  assert.deepEqual(moveStep(steps(), 1, -1).map((s) => s.kind), ["llm_extract", "render_pages"]);
  assert.deepEqual(moveStep(steps(), 0, -1).map((s) => s.kind), ["render_pages", "llm_extract"]);
  assert.deepEqual(moveStep(steps(), 1, 1).map((s) => s.kind), ["render_pages", "llm_extract"]);
});

test("moving a step does not mutate the list it was given", () => {
  const original = steps();
  moveStep(original, 1, -1);
  assert.deepEqual(original.map((s) => s.kind), ["render_pages", "llm_extract"]);
});

test("a new step arrives with the configuration its kind needs", () => {
  const added = addStep(steps(), "regex_refine");

  assert.equal(added.length, 3);
  assert.deepEqual(added[2], { kind: "regex_refine", config: { rules: [] } });
  assert.deepEqual(defaultConfigFor("render_pages"), { scale: 1.35 });
  assert.deepEqual(defaultConfigFor("llm_extract"), {});
});

test("removing a step leaves the others in order", () => {
  assert.deepEqual(removeStep(addStep(steps(), "regex_refine"), 1).map((s) => s.kind), [
    "render_pages",
    "regex_refine",
  ]);
});

test("changing one step's configuration leaves the others alone", () => {
  const changed = setStepConfig(steps(), 0, { scale: 2 });

  assert.deepEqual(changed[0].config, { scale: 2 });
  assert.deepEqual(changed[1].config, {});
});

test("the rules of a step are read even when the config is empty", () => {
  assert.deepEqual(rulesOf({ kind: "regex_refine", config: {} }), []);
  assert.deepEqual(rulesOf({ kind: "render_pages", config: { scale: 1 } }), []);
  assert.equal(rulesOf({ kind: "regex_refine", config: { rules: [emptyRule("date")] } }).length, 1);
});

test("a new rule targets the field it was created for and changes nothing yet", () => {
  const rule = emptyRule("total_amount");

  assert.equal(rule.entity, "total_amount");
  assert.equal(rule.when, "always");
  assert.equal(rule.source, "value");
});

test("a step is summarized by what it does, not by its kind", () => {
  assert.match(summarizeStep({ kind: "render_pages", config: { scale: 2 } }), /2/);
  assert.match(
    summarizeStep({ kind: "regex_refine", config: { rules: [emptyRule("date"), emptyRule("date")] } }),
    /2 rules/,
  );
  assert.match(summarizeStep({ kind: "regex_refine", config: { rules: [emptyRule("date")] } }), /1 rule\b/);
  assert.match(summarizeStep({ kind: "llm_extract", config: {} }), /model/i);
});

test("step labels come from the catalogue, and fall back to the raw kind", () => {
  const catalogue = [{ kind: "render_pages", label: "Render pages" }];

  assert.deepEqual(
    stepLabels([{ kind: "render_pages", config: {} }, { kind: "llm_extract", config: {} }], catalogue),
    ["Render pages", "llm_extract"],
  );
});

test("the page limit must be a whole number inside the backend range", () => {
  assert.equal(pageLimitProblem("1"), null);
  assert.equal(pageLimitProblem("100"), null);
  assert.match(pageLimitProblem("0") ?? "", /between 1 and 100/);
  assert.match(pageLimitProblem("101") ?? "", /between 1 and 100/);
  assert.match(pageLimitProblem("2.5") ?? "", /between 1 and 100/);
  assert.match(pageLimitProblem("") ?? "", /between 1 and 100/);
});
