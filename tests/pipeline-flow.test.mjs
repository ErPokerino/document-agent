import assert from "node:assert/strict";
import test from "node:test";
import { insertFlowStep, pipelineFlow, stepProblems } from "../lib/pipeline-flow.ts";

test("saved pipelines become a connected sequence without rewriting any settings", () => {
  const steps = [
    {kind: "document_ai_extract", config: {processor_ref: "invoice", processor_version: "v3.1", option: {kept: true}}},
    {kind: "regex_refine", config: {rules: [{entity: "date", pattern: "x"}]}},
    {kind: "regex_refine", config: {rules: []}},
  ];
  const before = structuredClone(steps);
  const graph = pipelineFlow(steps);
  assert.deepEqual(graph.nodes.map(n => n.id), ["input", "step-0", "step-1", "step-2", "output"]);
  assert.deepEqual(graph.edges.map(e => [e.source, e.target, e.insertAt]), [
    ["input", "step-0", 0], ["step-0", "step-1", 1], ["step-1", "step-2", 2], ["step-2", "output", 3],
  ]);
  assert.deepEqual(steps, before);
});

test("a node inserted on a connection goes exactly between its neighbours", () => {
  const steps = [{kind: "read_pdf_text", config: {feeds_model: false}}, {kind: "llm_extract", config: {custom: "keep"}}];
  const next = insertFlowStep(steps, 1, "document_ai_ocr");
  assert.deepEqual(next.map(s => s.kind), ["read_pdf_text", "document_ai_ocr", "llm_extract"]);
  assert.equal(next[0], steps[0]);
  assert.equal(next[2], steps[1]);
  assert.deepEqual(next[1].config, {processor_ref: "", processor_version: ""});
  assert.equal(steps.length, 2);
});

test("an empty pipeline still has an insertion point between PDF and output", () => {
  assert.deepEqual(pipelineFlow([]).edges.map(e => [e.source, e.target, e.insertAt]), [["input", "output", 0]]);
  assert.equal(insertFlowStep([], 0, "read_pdf_text")[0].kind, "read_pdf_text");
});

test("OCR fallback is visible as a conditional node while execution stays ordered", () => {
  const graph = pipelineFlow([{kind: "read_pdf_text", config: {}}, {kind: "document_ai_ocr", config: {only_without_pdf_text: true}}]);
  assert.equal(graph.nodes[2].conditional, true);
});

test("step errors match the full step number, not a shared prefix", () => {
  const problems = ["Step 1: missing input", "Step 10: missing processor", "No extraction step"];
  assert.deepEqual(stepProblems(problems, 0), [problems[0]]);
  assert.deepEqual(stepProblems(problems, 9), [problems[1]]);
});
