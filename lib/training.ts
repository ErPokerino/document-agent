/**
 * The training form and the model comparison, kept apart from React so their rules can be tested.
 *
 * Nothing here names an algorithm: what each one is called, whether it can
 * train here and which parameters it takes all come from the backend, so a
 * new algorithm needs no change in this file. The defaults mirror the backend
 * models, which validate again.
 */

import type {
  AlgorithmInfo,
  ArtifactSummary,
  EntityDefinition,
  ParameterSpec,
  TextFeatures,
  TrainingJobModel,
  TrainingRequest,
} from "./types";

export type ParameterValue = boolean | number | string;

export const DEFAULT_TEXT_FEATURES: TextFeatures = {
  analyzer: "char_wb",
  ngram_min: 3,
  ngram_max: 5,
  sublinear_tf: true,
  min_df: 1,
  max_df: 0.95,
  max_features: 200_000,
  max_characters: 20_000,
  reduce_to: null,
};

export type TrainingForm = {
  name: string;
  algorithm: string;
  datasets: string[];
  pipeline: string;
  entities: string[];
  inputFields: string[];
  text: TextFeatures;
  parameters: Record<string, ParameterValue>;
  cutoffEntity: string;
  cutoffBefore: string;
};

export function emptyTrainingForm(pipeline = ""): TrainingForm {
  return {
    name: "", algorithm: "", datasets: [], pipeline, entities: [], inputFields: [],
    text: { ...DEFAULT_TEXT_FEATURES }, parameters: {}, cutoffEntity: "", cutoffBefore: "",
  };
}

export function defaultParameters(algorithm: Pick<AlgorithmInfo, "parameters">): Record<string, ParameterValue> {
  return Object.fromEntries(algorithm.parameters.map((spec) => [spec.name, spec.default]));
}

/** Choosing an algorithm resets what belongs to the previous one, and keeps the rest. */
export function withAlgorithm(form: TrainingForm, algorithm: AlgorithmInfo): TrainingForm {
  return {
    ...form,
    algorithm: algorithm.id,
    parameters: defaultParameters(algorithm),
    inputFields: algorithm.takes_fields ? form.inputFields : [],
    text: { ...form.text, reduce_to: algorithm.default_reduce_to },
  };
}

export function parameterProblem(spec: ParameterSpec, value: ParameterValue | undefined): string | null {
  if (value === undefined || value === "") return `${spec.label} is empty.`;
  if (spec.kind === "int" && (typeof value !== "number" || !Number.isInteger(value))) return `${spec.label} must be a whole number.`;
  if (spec.kind === "float" && (typeof value !== "number" || Number.isNaN(value))) return `${spec.label} must be a number.`;
  if (spec.kind === "choice" && !spec.choices.includes(String(value))) return `${spec.label} must be one of: ${spec.choices.join(", ")}.`;
  if (typeof value === "number") {
    if (spec.minimum !== null && spec.minimum !== undefined && value < spec.minimum) return `${spec.label} must be at least ${spec.minimum}.`;
    if (spec.maximum !== null && spec.maximum !== undefined && value > spec.maximum) return `${spec.label} must be at most ${spec.maximum}.`;
  }
  return null;
}

/** What stops the form from being sent, in the order a person fills it in. */
export function trainingProblems(form: TrainingForm, algorithm?: AlgorithmInfo): string[] {
  const problems: string[] = [];
  if (!algorithm) problems.push("Choose an algorithm.");
  else if (algorithm.status !== "available") problems.push(`${algorithm.label} cannot train on this machine.`);
  if (!form.name.trim()) problems.push("Name the model.");
  if (!form.datasets.length) problems.push("Choose at least one dataset to learn from.");
  if (!form.pipeline) problems.push("Choose the pipeline whose reading steps produce the text.");
  if (!form.entities.length) problems.push("Choose at least one field to predict.");
  if (form.text.ngram_max < form.text.ngram_min) problems.push("The largest n-gram cannot be shorter than the smallest.");
  if (form.cutoffBefore && !form.cutoffEntity) problems.push("A cutoff needs the date field it is read from.");
  for (const spec of algorithm?.parameters ?? []) {
    const problem = parameterProblem(spec, form.parameters[spec.name]);
    if (problem) problems.push(problem);
  }
  return problems;
}

export function trainingRequest(form: TrainingForm): TrainingRequest {
  const cutoff = Boolean(form.cutoffBefore && form.cutoffEntity);
  return {
    name: form.name.trim(),
    algorithm: form.algorithm,
    datasets: form.datasets,
    pipeline: form.pipeline,
    entities: form.entities,
    input_fields: form.inputFields,
    text: form.text,
    parameters: form.parameters,
    cutoff_entity: cutoff ? form.cutoffEntity : null,
    cutoff_before: cutoff ? form.cutoffBefore : null,
  };
}

export const FAMILY_LABELS: Record<AlgorithmInfo["family"], { title: string; blurb: string }> = {
  neighbours: { title: "Neighbours", blurb: "Copy the labels of the most similar labelled documents." },
  linear: { title: "Linear", blurb: "One weight per feature and class; fast, and readable from few documents." },
  boosting: { title: "Gradient boosting", blurb: "Ensembles of trees; strong on dense features and field inputs." },
  foundation: { title: "Foundation models", blurb: "Pre-trained models that predict with little or no training here." },
};

const FAMILY_ORDER: AlgorithmInfo["family"][] = ["neighbours", "linear", "boosting", "foundation"];

export function groupAlgorithms(algorithms: AlgorithmInfo[]): { family: AlgorithmInfo["family"]; algorithms: AlgorithmInfo[] }[] {
  return FAMILY_ORDER
    .map((family) => ({ family, algorithms: algorithms.filter((algorithm) => algorithm.family === family) }))
    .filter((group) => group.algorithms.length > 0);
}

export const STATUS_LABELS: Record<AlgorithmInfo["status"], string> = {
  available: "Ready",
  not_installed: "Not installed",
  not_connected: "Not connected",
};

/**
 * The fields worth predicting from the nearest document, first.
 *
 * Any field can be learned, but a category is what these models are for; an
 * amount or a document number is not shared between invoices.
 */
export function predictableFields(entities: EntityDefinition[]): EntityDefinition[] {
  return [...entities].sort((a, b) => Number(b.format === "category") - Number(a.format === "category"));
}

export function dateFields(entities: EntityDefinition[]): EntityDefinition[] {
  return entities.filter((entity) => entity.format === "date");
}

export function jobProgress(job: TrainingJobModel): string {
  if (job.status === "running") {
    if (job.phase && job.phase !== "reading") return job.phase[0].toUpperCase() + job.phase.slice(1);
    return job.total ? `Reading ${job.done} of ${job.total} documents` : "Starting";
  }
  if (job.status === "completed" && job.kind === "fine_tuning_export") return `${job.examples} examples from ${job.total} documents`;
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

export type LeaderboardRow = {
  artifact: ArtifactSummary;
  accuracy: number | null;
  macroF1: number | null;
  documents: number | null;
};

/**
 * Models side by side, one table per field they predict.
 *
 * Figures measured by different methods — leave-one-out against k-fold —
 * are not the same measurement, so each row says which it is; and only a Lab
 * run over a separate dataset is a measurement of new documents.
 */
export function leaderboard(artifacts: ArtifactSummary[]): { entity: string; rows: LeaderboardRow[] }[] {
  const entities = [...new Set(artifacts.flatMap((artifact) => artifact.entities))].sort();
  return entities.map((entity) => ({
    entity,
    rows: artifacts
      .filter((artifact) => artifact.entities.includes(entity))
      .map((artifact) => {
        const measured = artifact.validation[entity];
        return { artifact, accuracy: measured?.accuracy ?? null, macroF1: measured?.macro_f1 ?? null, documents: measured?.documents ?? null };
      })
      .sort((a, b) => (b.accuracy ?? -1) - (a.accuracy ?? -1) || (b.macroF1 ?? -1) - (a.macroF1 ?? -1)),
  }));
}

const READERS = new Set(["read_pdf_text", "document_ai_ocr", "document_ai_layout"]);
// Any step that fills fields ends the reading: training uses only what comes before.
const FILLERS = new Set(["llm_extract", "document_ai_extract", "regex_refine", "master_data_lookup", "supplier_rules", "artifact_predict", "resolve_candidates"]);

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
