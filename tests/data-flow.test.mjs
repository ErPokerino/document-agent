import assert from "node:assert/strict";
import test from "node:test";

import { describeDataFlow } from "../lib/data-flow.ts";

test("a local model and no cloud step keeps everything on the machine", () => {
  const flow = describeDataFlow("lm_studio", ["render_pages", "llm_extract"]);

  assert.equal(flow.leavesTheMachine, false);
  assert.match(flow.heading, /private/i);
  assert.match(flow.detail, /this machine/i);
});

test("a hosted model sends the pages to Google", () => {
  const flow = describeDataFlow("gemini", ["render_pages", "llm_extract"]);

  assert.equal(flow.leavesTheMachine, true);
  assert.match(flow.detail, /Gemini/);
});

test("Document AI sends the pages to Google even when the model is local", () => {
  // The claim that used to be made here — "processed exclusively by the local
  // model" — was false for every OCR pipeline.
  const flow = describeDataFlow("lm_studio", ["document_ai_ocr", "llm_extract"]);

  assert.equal(flow.leavesTheMachine, true);
  assert.match(flow.detail, /Document AI/);
  assert.match(flow.detail, /this machine/);
});

test("the Layout Parser counts as much as OCR does", () => {
  assert.equal(describeDataFlow("lm_studio", ["document_ai_layout"]).leavesTheMachine, true);
});

test("both destinations are named when both are used", () => {
  const flow = describeDataFlow("gemini", ["document_ai_ocr", "llm_extract"]);

  assert.match(flow.detail, /Document AI/);
  assert.match(flow.detail, /Gemini/);
});

test("an unknown pipeline shape claims nothing either way", () => {
  const flow = describeDataFlow("lm_studio", []);

  assert.equal(flow.leavesTheMachine, false);
});
