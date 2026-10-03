/**
 * The training form, kept apart from React so its rules can be tested.
 *
 * The defaults mirror KnnParameters in the backend; the backend validates
 * again, so a drift here is refused rather than silently trained.
 */

import type { ArtifactSummary, EntityDefinition, KnnParameters, KnnTrainingRequest, TrainingJobModel } from "./types";

export const DEFAULT_KNN_PARAMETERS: KnnParameters = {
  analyzer: "char_wb",
  ngram_min: 3,
  ngram_max: 5,
  sublinear_tf: true,
  min_df: 1,
  max_df: 0.95,
  max_features: 200_000,
  max_characters: 20_000,
  k: 1,
  weighting: "distance",
};

export type TrainingForm = {
  name: string;
  datasets: string[];
  pipeline: string;
  entities: string[];
  parameters: KnnParameters;
  cutoffEntity: string;
  cutoffBefore: string;
};

export function emptyTrainingForm(pipeline = ""): TrainingForm {
  return { name: "", datasets: [], pipeline, entities: [], parameters: { ...DEFAULT_KNN_PARAMETERS }, cutoffEntity: "", cutoffBefore: "" };
}

/** What stops the form from being sent, in the order a person fills it in. */
export function trainingProblems(form: TrainingForm): string[] {
  const problems: string[] = [];
  if (!form.name.trim()) problems.push("Name the model.");
  if (!form.datasets.length) problems.push("Choose at least one dataset to learn from.");
  if (!form.pipeline) problems.push("Choose the pipeline whose reading steps produce the text.");
  if (!form.entities.length) problems.push("Choose at least one field to predict.");
  if (form.parameters.ngram_max < form.parameters.ngram_min) problems.push("The largest n-gram cannot be shorter than the smallest.");
  if (form.cutoffBefore && !form.cutoffEntity) problems.push("A cutoff needs the date field it is read from.");
  return problems;
}

export function trainingRequest(form: TrainingForm): KnnTrainingRequest {
  const cutoff = Boolean(form.cutoffBefore && form.cutoffEntity);
  return {
    name: form.name.trim(),
    datasets: form.datasets,
    pipeline: form.pipeline,
    entities: form.entities,
    parameters: form.parameters,
    cutoff_entity: cutoff ? form.cutoffEntity : null,
    cutoff_before: cutoff ? form.cutoffBefore : null,
  };
}

/**
 * The fields worth predicting from the nearest document, first.
 *
 * Any field can be learned, but a category is what a neighbour's label is the
 * right answer for; an amount or a document number is not shared between
 * invoices and would be copied wrongly.
 */
export function predictableFields(entities: EntityDefinition[]): EntityDefinition[] {
  return [...entities].sort((a, b) => Number(b.format === "category") - Number(a.format === "category"));
}

export function dateFields(entities: EntityDefinition[]): EntityDefinition[] {
  return entities.filter((entity) => entity.format === "date");
}

export function jobProgress(job: TrainingJobModel): string {
  if (job.status === "running") return job.total ? `Reading ${job.done} of ${job.total} documents` : "Starting";
  if (job.status === "completed") return `Trained on ${job.total - job.skipped.length} of ${job.total} documents`;
  if (job.status === "cancelled") return "Cancelled";
  return job.error ?? "Failed";
}

/** A short line for a trained model's provenance. */
export function provenance(artifact: ArtifactSummary): string {
  const parts = [
    `${artifact.documents} documents from ${artifact.datasets.join(", ") || "an imported model"}`,
    artifact.cutoff_before ? `dated before ${artifact.cutoff_before} by ${artifact.cutoff_entity}` : "",
    artifact.reader.length ? `text read by ${artifact.reader.join(" → ")}` : "",
  ];
  return parts.filter(Boolean).join(" · ");
}

const READERS = new Set(["read_pdf_text", "document_ai_ocr", "document_ai_layout"]);
// Any step that fills fields ends the reading: training uses only what comes before.
const FILLERS = new Set(["llm_extract", "document_ai_extract", "regex_refine", "master_data_lookup", "supplier_rules", "artifact_predict"]);

/** The reading steps training would use from a pipeline, as the backend picks them. */
export function readingKinds(kinds: string[]): string[] {
  const readers: string[] = [];
  for (const kind of kinds) {
    if (FILLERS.has(kind)) break;
    if (READERS.has(kind)) readers.push(kind);
  }
  return readers;
}

/**
 * Where the documents go while training reads them, said before it starts.
 *
 * A stored reading is reused, so only documents without one are sent. Which
 * those are is not known until the cache is asked, so the sentence names the
 * condition rather than a count.
 */
export function trainingDataFlow(kinds: string[], onlyScans: boolean): string {
  const readers = readingKinds(kinds);
  if (!readers.length) return "This pipeline reads no text before it fills fields, so it cannot train a model.";
  if (!readers.some((kind) => kind.startsWith("document_ai_"))) return "Text is read on this machine; no document leaves it.";
  if (onlyScans) return "PDFs without text of their own that have no stored reading are sent to Google Document AI and billed per page.";
  return "Documents without a stored reading are sent to Google Document AI and billed per page.";
}
