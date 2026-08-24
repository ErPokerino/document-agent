import type { Evaluation } from "./types";

export type EvaluationFilters = {
  model: string;
  pipeline: string;
  // Where the run happened. Same three choices as the model list in LLM, in
  // the same words, so the two places do not describe one idea differently.
  runsOn: "" | "lm_studio" | "gemini";
  since: string;
  minAccuracy: string;
  minDocuments: string;
};

export const emptyFilters: EvaluationFilters = {
  model: "",
  pipeline: "",
  runsOn: "",
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
    if (filters.model && evaluation.model !== filters.model) return false;
    if (filters.pipeline && evaluation.pipeline !== filters.pipeline) return false;
    // A payload from a backend older than the provider column has no field at
    // all; those runs were local, because hosted models came later.
    if (filters.runsOn && (evaluation.provider ?? "lm_studio") !== filters.runsOn) return false;
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

export function distinctPipelines(evaluations: Evaluation[]): string[] {
  return [...new Set(evaluations.map((evaluation) => evaluation.pipeline))].sort();
}

export function hasActiveFilters(filters: EvaluationFilters): boolean {
  return Object.values(filters).some((value) => value.trim() !== "");
}
