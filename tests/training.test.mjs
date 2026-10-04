import assert from "node:assert/strict";
import test from "node:test";

import {
  emptyTrainingForm,
  groupAlgorithms,
  jobProgress,
  leaderboard,
  parameterProblem,
  predictableFields,
  readingKinds,
  trainingDataFlow,
  trainingProblems,
  trainingRequest,
  withAlgorithm,
} from "../lib/training.ts";

const logistic = {
  id: "logistic_regression", label: "Logistic regression", family: "linear", description: "", status: "available",
  runs: "local", install: null, reads_text: true, takes_fields: true, default_reduce_to: null,
  parameters: [{ name: "C", label: "C", kind: "float", default: 1, minimum: 0.0001, maximum: 10000, step: 0.1, choices: [], help: "" }],
};
const knn = { ...logistic, id: "knn_tfidf", family: "neighbours", takes_fields: false, parameters: [] };
const boosting = { ...logistic, id: "lightgbm", family: "boosting", default_reduce_to: 256, parameters: [] };
const remote = { ...logistic, id: "jev", label: "Jev", family: "foundation", status: "not_connected", parameters: [] };

const filled = () => ({ ...withAlgorithm(emptyTrainingForm("Local text"), logistic), name: "suppliers", datasets: ["2025"], entities: ["id_subject"] });

test("a complete form has nothing stopping it", () => {
  assert.deepEqual(trainingProblems(filled(), logistic), []);
});

test("an empty form says what is missing, in the order it is filled in", () => {
  assert.deepEqual(trainingProblems(emptyTrainingForm()), [
    "Choose an algorithm.",
    "Name the model.",
    "Choose at least one dataset to learn from.",
    "Choose the pipeline whose reading steps produce the text.",
    "Choose at least one field to predict.",
  ]);
});

test("an algorithm that cannot train here stops the form", () => {
  assert.ok(trainingProblems({ ...filled(), algorithm: "jev" }, remote).includes("Jev cannot train on this machine."));
});

test("choosing an algorithm brings its defaults and its text reduction", () => {
  const form = withAlgorithm({ ...filled(), inputFields: ["currency"] }, boosting);

  assert.equal(form.text.reduce_to, 256);
  assert.deepEqual(form.inputFields, ["currency"]);
  assert.deepEqual(withAlgorithm(form, knn).inputFields, []);
  assert.equal(withAlgorithm(form, logistic).parameters.C, 1);
});

test("a parameter outside its bounds is named", () => {
  assert.equal(parameterProblem(logistic.parameters[0], 0), "C must be at least 0.0001.");
  assert.equal(parameterProblem(logistic.parameters[0], 2), null);
});

test("a half-filled cutoff is not sent as one", () => {
  const request = trainingRequest({ ...filled(), cutoffEntity: "date" });

  assert.equal(request.cutoff_entity, null);
  assert.equal(request.algorithm, "logistic_regression");
});

test("algorithms are grouped by family in a fixed order", () => {
  assert.deepEqual(groupAlgorithms([remote, boosting, knn, logistic]).map((group) => group.family), ["neighbours", "linear", "boosting", "foundation"]);
});

test("categorical fields are offered first", () => {
  const ordered = predictableFields([
    { name: "total_amount", format: "decimal", description: "x", source: "model", categories: [] },
    { name: "id_subject", format: "category", description: "x", source: "derived", categories: [] },
  ]);

  assert.equal(ordered[0].name, "id_subject");
});

test("a running job says which phase it is in", () => {
  const job = { id: 1, kind: "lightgbm", name: "x", created_at: "", status: "running", total: 10, done: 10, skipped: [], output: null, examples: 0 };

  assert.equal(jobProgress({ ...job, phase: "reading", done: 4 }), "Reading 4 of 10 documents");
  assert.equal(jobProgress({ ...job, phase: "validating, fold 2 of 5" }), "Validating, fold 2 of 5");
});

test("a finished job counts the documents it could not read", () => {
  assert.equal(
    jobProgress({ id: 1, kind: "knn_tfidf", name: "x", created_at: "", status: "completed", total: 10, done: 10, skipped: ["a: no text"], output: null, examples: 0, phase: null }),
    "Trained on 9 of 10 documents",
  );
});

test("the comparison has one table per field, best first", () => {
  const artifact = (id, accuracy) => ({ id, entities: ["id_subject"], validation: { id_subject: { documents: 10, accuracy, macro_f1: accuracy, classes: 3 } } });

  const [table] = leaderboard([artifact("a", 0.5), artifact("b", 0.9)]);

  assert.equal(table.entity, "id_subject");
  assert.deepEqual(table.rows.map((row) => row.artifact.id), ["b", "a"]);
});

test("training reads only the steps before the first one that fills fields", () => {
  assert.deepEqual(readingKinds(["read_pdf_text", "document_ai_ocr", "llm_extract", "document_ai_layout"]), ["read_pdf_text", "document_ai_ocr"]);
});

test("a local reader is said to keep the documents on the machine", () => {
  assert.match(trainingDataFlow(["read_pdf_text", "llm_extract"], false), /no document leaves it/);
});

test("an OCR fallback is said to send only scans without a stored reading", () => {
  assert.match(trainingDataFlow(["read_pdf_text", "document_ai_ocr", "llm_extract"], true), /without text of their own/);
});
