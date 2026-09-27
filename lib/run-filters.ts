import { engineKey } from "./extraction-engine.ts";
import type { Evaluation } from "./types";

export type EvaluationFilters = {
  model: string[];
  pipeline: string[];
  // Accuracy on one dataset says nothing about accuracy on another, so
  // comparing approaches means holding the dataset still.
  dataset: string[];
  // Where the run happened. Same three choices as the model list in LLM, in
  // the same words, so the two places do not describe one idea differently.
  runsOn: string[];
  since: string;
  minAccuracy: string;
  minDocuments: string;
};

export const emptyFilters: EvaluationFilters = {
  model: [],
  pipeline: [],
  dataset: [],
  runsOn: [],
  since: "",
  minAccuracy: "",
  minDocuments: "",
};

/** An empty or malformed box means "no threshold", never "hide everything". */
function threshold(raw: string): number | null {
  const value = Number(raw);
  return raw.trim() && Number.isFinite(value) ? value : null;
}

export function filterEvaluations(
  evaluations: Evaluation[],
  filters: EvaluationFilters,
): Evaluation[] {
  const minAccuracy = threshold(filters.minAccuracy);
  const minDocuments = threshold(filters.minDocuments);

  return evaluations.filter((evaluation) => {
    if (filters.model.length && !filters.model.includes(engineKey(evaluation))) return false;
    if (filters.pipeline.length && !filters.pipeline.includes(evaluation.pipeline)) return false;
    if (filters.dataset.length && !filters.dataset.includes(evaluation.dataset)) return false;
    // A payload from a backend older than the provider column has no field at
    // all; those runs were local, because hosted models came later.
    if (filters.runsOn.length && !filters.runsOn.includes(evaluation.provider ?? "lm_studio")) return false;
    // created_at is ISO, so a date-only prefix compares correctly as text.
    if (filters.since && evaluation.created_at.slice(0, 10) < filters.since) return false;
    if (minAccuracy !== null) {
      const accuracy = evaluation.metrics.accuracy;
      if (accuracy === null || accuracy * 100 < minAccuracy) return false;
    }
    if (minDocuments !== null && evaluation.total_documents < minDocuments) return false;
    return true;
  });
}

export function distinctModels(evaluations: Evaluation[]): string[] {
  return [...new Set(evaluations.map((evaluation) => evaluation.model))].sort();
}

export function distinctDatasets(evaluations: Evaluation[]): string[] {
  return [...new Set(evaluations.map((evaluation) => evaluation.dataset))].sort();
}

export function distinctPipelines(evaluations: Evaluation[]): string[] {
  return [...new Set(evaluations.map((evaluation) => evaluation.pipeline))].sort();
}

/**
 * What the filters are keeping out of view, or null when they keep nothing.
 *
 * Filters live in the address, so they outlast the moment they were chosen. A
 * Gemini run on "Read PDF text" was started under "OCR then LLM · On this
 * machine" and never appeared, which read as a run that had not been recorded.
 */
export function hiddenRunsNote(evaluations: Evaluation[], visible: Evaluation[]): string | null {
  const shown = new Set(visible.map((evaluation) => evaluation.id));
  const hidden = evaluations.filter((evaluation) => !shown.has(evaluation.id));
  if (hidden.length === 0) return null;
  const running = hidden.find((evaluation) => evaluation.status === "running");
  const count = hidden.length === 1
    ? `1 of ${evaluations.length} runs is hidden by these filters.`
    : `${hidden.length} of ${evaluations.length} runs are hidden by these filters.`;
  return running ? `${count} Run #${running.id}, in progress, is among them.` : count;
}

export function hasActiveFilters(filters: EvaluationFilters): boolean {
  return Object.values(filters).some((value) => Array.isArray(value) ? value.length > 0 : value.trim() !== "");
}
