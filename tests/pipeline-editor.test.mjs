import assert from "node:assert/strict";
import test from "node:test";

import {
  addStep,
  defaultConfigFor,
  emptyRule,
  groupCatalogue,
  moveStep,
  removeStep,
  rulesOf,
  pageLimitProblem,
  setStepConfig,
  stepLabel,
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

test("every kind of step describes itself, not the one after it", () => {
  // A step with no case of its own used to fall through and describe rules
  // it does not have.
  assert.match(summarizeStep({ kind: "document_ai_ocr", config: {} }), /OCR/i);
  assert.match(summarizeStep({ kind: "document_ai_layout", config: {} }), /layout/i);
  assert.doesNotMatch(summarizeStep({ kind: "document_ai_ocr", config: {} }), /rule/i);
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

test("steps are offered grouped by what they do", () => {
  const catalogue = [
    { kind: "render_pages", label: "Render pages" },
    { kind: "document_ai_ocr", label: "Document AI OCR" },
    { kind: "llm_extract", label: "LLM extraction" },
    { kind: "regex_refine", label: "Regex refinement" },
    { kind: "master_data_lookup", label: "Master data lookup" },
  ];

  const grouped = groupCatalogue(catalogue);

  assert.deepEqual(grouped.map((group) => group.title), [
    "Read the document",
    "Ask a model",
    "Derived",
    "Post processing",
  ]);
  assert.deepEqual(grouped[0].entries.map((entry) => entry.kind), ["render_pages", "document_ai_ocr"]);
  // Deriving a field and tidying one up are different jobs, and a rule can be
  // applied to a derived field just as well as to an extracted one.
  assert.deepEqual(grouped[2].entries.map((entry) => entry.kind), ["master_data_lookup"]);
  assert.deepEqual(grouped[3].entries.map((entry) => entry.kind), ["regex_refine"]);
});

test("a step nobody grouped still gets offered", () => {
  const grouped = groupCatalogue([{ kind: "something_new", label: "Something new" }]);

  assert.equal(grouped.at(-1).entries.at(-1).kind, "something_new");
});

test("an empty catalogue produces no empty groups", () => {
  assert.deepEqual(groupCatalogue([]), []);
});

test("a lookup step is summarized by the field it fills", () => {
  const step = { kind: "master_data_lookup", config: { source_entity: "supplier_name", target_entity: "id_subject" } };

  assert.match(summarizeStep(step), /supplier_name/);
  assert.match(summarizeStep(step), /id_subject/);
});

test("a lookup step that is not configured yet says so instead of pretending", () => {
  assert.match(summarizeStep({ kind: "master_data_lookup", config: {} }), /not configured/i);
});

test("a new lookup step starts with the defaults the backend would use", () => {
  assert.deepEqual(defaultConfigFor("master_data_lookup"), {
    source_entity: "",
    target_entity: "",
    algorithm: "combined",
    minimum_similarity: 0.75,
  });
});

test("every step the backend can run has a readable name", () => {
  // The map went two kinds without one, and a run built on either was
  // described in Lab as `document_ai_extract → supplier_rules`. The type keeps
  // it exhaustive now; this keeps the fallback honest about what it is for.
  const kinds = [
    "render_pages",
    "document_ai_ocr",
    "document_ai_layout",
    "document_ai_extract",
    "llm_extract",
    "regex_refine",
    "master_data_lookup",
    "supplier_rules",
  ];
  for (const kind of kinds) {
    assert.notEqual(stepLabel(kind), kind, kind);
  }
});

test("a step kind that no longer exists is shown as itself", () => {
  // A run recorded months ago must stay readable.
  assert.equal(stepLabel("some_retired_step"), "some_retired_step");
});
