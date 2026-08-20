import type { Evaluation } from "./types";

export type EvaluationFilters = {
  model: string;
  since: string;
  minAccuracy: string;
  minDocuments: string;
};

export const emptyFilters: EvaluationFilters = {
  model: "",
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

export function hasActiveFilters(filters: EvaluationFilters): boolean {
  return Object.values(filters).some((value) => value.trim() !== "");
}
