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

test("reading the text a PDF carries keeps the document on the machine", () => {
  const flow = describeDataFlow("lm_studio", ["read_pdf_text", "llm_extract"]);

  assert.equal(flow.leavesTheMachine, false);
});

test("an OCR that reads only PDFs without text still counts as leaving the machine", () => {
  // One scan in a batch is enough for pages to reach Google.
  const flow = describeDataFlow("lm_studio", ["read_pdf_text", "document_ai_ocr", "llm_extract"], true);

  assert.equal(flow.leavesTheMachine, true);
  assert.match(flow.detail, /no text of its own/);
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

test("the Custom Extractor sends the pages to Google, model or no model", () => {
  // It reads the page at Google and answers from there. Calling that private
  // processing because no local model was involved was the same false claim
  // this module exists to prevent.
  const flow = describeDataFlow("lm_studio", ["document_ai_extract"]);

  assert.equal(flow.leavesTheMachine, true);
  assert.match(flow.detail, /Document AI/);
});

test("a pipeline that calls no model says so instead of claiming one answers", () => {
  const flow = describeDataFlow("lm_studio", ["document_ai_extract"]);

  assert.match(flow.detail, /no language model/i);
  assert.doesNotMatch(flow.detail, /the model answers/i);
});

test("a hosted model that is never called is not a destination", () => {
  // Gemini selected in the corner does not mean Gemini sees the document.
  const flow = describeDataFlow("gemini", ["document_ai_extract"]);

  assert.doesNotMatch(flow.detail, /Gemini/);
  assert.match(flow.detail, /no language model/i);
});

test("a self-hosted model server is named as where the fields are extracted", () => {
  const flow = describeDataFlow("model_server", ["render_pages", "llm_extract"]);

  assert.equal(flow.leavesTheMachine, true);
  assert.match(flow.heading, /model server/i);
  assert.doesNotMatch(flow.heading, /Google/);
  assert.match(flow.detail, /model server/);
});

test("Document AI and a model server are both named", () => {
  const flow = describeDataFlow("model_server", ["document_ai_ocr", "llm_extract"]);

  assert.match(flow.heading, /Google and the model server/);
});
