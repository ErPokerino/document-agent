import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_KNN_PARAMETERS,
  emptyTrainingForm,
  jobProgress,
  predictableFields,
  readingKinds,
  trainingDataFlow,
  trainingProblems,
  trainingRequest,
} from "../lib/training.ts";

const filled = () => ({ ...emptyTrainingForm("Local text"), name: "suppliers", datasets: ["2025"], entities: ["id_subject"] });

test("a complete form has nothing stopping it", () => {
  assert.deepEqual(trainingProblems(filled()), []);
});

test("an empty form says what is missing, in the order it is filled in", () => {
  assert.deepEqual(trainingProblems(emptyTrainingForm()), [
    "Name the model.",
    "Choose at least one dataset to learn from.",
    "Choose the pipeline whose reading steps produce the text.",
    "Choose at least one field to predict.",
  ]);
});

test("a cutoff without the date field it is read from is refused", () => {
  assert.ok(trainingProblems({ ...filled(), cutoffBefore: "2026-01-01" }).includes("A cutoff needs the date field it is read from."));
});

test("a half-filled cutoff is not sent as one", () => {
  const request = trainingRequest({ ...filled(), cutoffEntity: "date" });

  assert.equal(request.cutoff_entity, null);
  assert.equal(request.cutoff_before, null);
});

test("the defaults are character n-grams, nearest single neighbour", () => {
  assert.equal(DEFAULT_KNN_PARAMETERS.analyzer, "char_wb");
  assert.equal(DEFAULT_KNN_PARAMETERS.k, 1);
});

test("categorical fields are offered first", () => {
  const ordered = predictableFields([
    { name: "total_amount", format: "decimal", description: "x", source: "model", categories: [] },
    { name: "id_subject", format: "category", description: "x", source: "derived", categories: [] },
  ]);

  assert.equal(ordered[0].name, "id_subject");
});

test("a finished job counts the documents it could not read", () => {
  assert.equal(
    jobProgress({ id: 1, kind: "knn_tfidf", name: "x", created_at: "", status: "completed", total: 10, done: 10, skipped: ["a: no text"] }),
    "Trained on 9 of 10 documents",
  );
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
