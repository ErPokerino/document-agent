import assert from "node:assert/strict";
import test from "node:test";

import { runWarning } from "../lib/run-warning.ts";

const localModel = {
  id: "qwen/qwen3.6-35b-a3b",
  name: "Qwen3.6 35B A3B",
  provider: "lm_studio",
  requires_safe_profile: true,
  vision: true,
};
const hosted = { ...localModel, id: "gemini-3.7-flash", provider: "gemini" };
const imageSteps = ["render_pages", "llm_extract"];
const textSteps = ["document_ai_ocr", "llm_extract"];

function run(overrides = {}) {
  return {
    id: 1,
    created_at: "2026-08-24T06:59:36+00:00",
    finished_at: "2026-08-24T07:31:58+00:00",
    model: "qwen/qwen3.6-35b-a3b",
    pipeline: "Vision extraction",
    status: "completed",
    max_pages: 1,
    average_elapsed_ms: 184000,
    succeeded_documents: 10,
    ...overrides,
  };
}

test("with no history it states the configuration and predicts nothing", () => {
  const warning = runWarning(localModel, imageSteps, [], "Vision extraction") ?? "";
  assert.match(warning, /processor/i);
  // The two claims this replaced: a duration this machine cannot know for any
  // other machine, and a page count that is a per-pipeline setting.
  assert.doesNotMatch(warning, /minute|second|hour/i);
  assert.doesNotMatch(warning, /one full page|one page/i);
});

test("with history it reports what was measured, not what is expected", () => {
  const warning = runWarning(localModel, imageSteps, [run()], "Vision extraction") ?? "";
  assert.match(warning, /184\.0 s/);
  assert.match(warning, /Vision extraction/);
  // The page limit the number was measured at, so a reader who has changed it
  // since can see the measurement no longer describes their next run.
  assert.match(warning, /1 page/);
});

test("a measurement from another model or pipeline is not borrowed", () => {
  const otherModel = [run({ model: "qwen/qwen3.8-27b" })];
  const otherPipeline = [run({ pipeline: "OCR then model" })];
  for (const history of [otherModel, otherPipeline]) {
    const warning = runWarning(localModel, imageSteps, history, "Vision extraction") ?? "";
    assert.doesNotMatch(warning, /184\.0 s/);
  }
});

test("a run that never produced an average is not a measurement", () => {
  const unfinished = [run({ status: "running", finished_at: null, average_elapsed_ms: null })];
  const warning = runWarning(localModel, imageSteps, unfinished, "Vision extraction") ?? "";
  assert.doesNotMatch(warning, /averaged/);
});

test("the most recent measurement wins", () => {
  const history = [
    run({ id: 1, created_at: "2026-08-20T10:00:00+00:00", average_elapsed_ms: 999000 }),
    run({ id: 2, created_at: "2026-08-24T10:00:00+00:00", average_elapsed_ms: 184000 }),
  ];
  const warning = runWarning(localModel, imageSteps, history, "Vision extraction") ?? "";
  assert.match(warning, /184\.0 s/);
  assert.doesNotMatch(warning, /999/);
});

test("the page limit is read from the run, never assumed", () => {
  const warning = runWarning(localModel, imageSteps, [run({ max_pages: 3 })], "Vision extraction") ?? "";
  assert.match(warning, /3 pages/);
});

test("nothing is said when there is nothing structural to say", () => {
  assert.equal(runWarning(undefined, imageSteps, [], "Vision extraction"), null);
  assert.equal(runWarning(hosted, imageSteps, [], "Vision extraction"), null);
  assert.equal(runWarning(localModel, textSteps, [], "OCR then model"), null);
  assert.equal(
    runWarning({ ...localModel, requires_safe_profile: false }, imageSteps, [], "Vision extraction"),
    null,
  );
});

test("nothing is recommended, in either branch", () => {
  for (const history of [[], [run()]]) {
    const warning = runWarning(localModel, imageSteps, history, "Vision extraction") ?? "";
    assert.doesNotMatch(warning, /instead|should|try |consider|recommend|expect/i);
  }
});
