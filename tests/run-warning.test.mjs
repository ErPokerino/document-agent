import assert from "node:assert/strict";
import test from "node:test";

import { runWarning } from "../lib/run-warning.ts";

const model = (overrides = {}) => ({
  id: "m",
  name: "M",
  provider: "lm_studio",
  vision: true,
  requires_safe_profile: false,
  ...overrides,
});

test("a small local model rendering pages is not worth warning about", () => {
  assert.equal(runWarning(model(), ["render_pages", "llm_extract"]), null);
});

test("a model kept off the GPU that is also sent images is", () => {
  // qwen3.6-35b-a3b took 136 seconds on the first document and crashed the
  // runtime on the second.
  const warning = runWarning(model({ requires_safe_profile: true }), ["render_pages", "llm_extract"]);

  assert.match(warning ?? "", /minutes/);
  // States what the configuration implies; recommends nothing.
  assert.doesNotMatch(warning ?? "", /OCR|instead|should|try/i);
});

test("the same model reading text instead is fine", () => {
  assert.equal(runWarning(model({ requires_safe_profile: true }), ["document_ai_ocr", "llm_extract"]), null);
});

test("a hosted model is never the slow case, whatever the pipeline does", () => {
  const hosted = model({ provider: "gemini", requires_safe_profile: true });

  assert.equal(runWarning(hosted, ["render_pages", "llm_extract"]), null);
});

test("nothing is claimed about a model that is not there", () => {
  assert.equal(runWarning(undefined, ["render_pages", "llm_extract"]), null);
});
