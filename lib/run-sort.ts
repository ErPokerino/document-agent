import type { Evaluation } from "./types";

export type SortKey =
  | "status"
  | "id"
  | "created_at"
  | "model"
  | "total_documents"
  | "total_elapsed_ms"
  | "max_pages"
  | "accuracy"
  | "cost";

export type SortDirection = "asc" | "desc";
export type Sort = { key: SortKey; direction: SortDirection };

const TEXT_KEYS: SortKey[] = ["status", "model", "created_at"];

/** What a run cost, which is derived from prices rather than stored on it. */
export type CostOf = (evaluation: Evaluation) => number | null | undefined;

function value(
  evaluation: Evaluation,
  key: SortKey,
  costOf: CostOf | undefined,
): number | string | null {
  if (key === "accuracy") return evaluation.metrics.accuracy;
  // Cost is not a column on a run: it depends on rates that can be edited, so
  // it is computed where it is shown and passed in here.
  if (key === "cost") return costOf ? costOf(evaluation) ?? null : null;
  return evaluation[key];
}

export function sortEvaluations(
  evaluations: Evaluation[],
  key: SortKey,
  direction: SortDirection,
  costOf?: CostOf,
): Evaluation[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...evaluations].sort((left, right) => {
    const a = value(left, key, costOf);
    const b = value(right, key, costOf);

    // Missing data sinks either way: a run with no accuracy should not take the
    // top of the table just because it has nothing to compare.
    if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
    if (b === null || b === undefined) return -1;

    if (TEXT_KEYS.includes(key)) {
      return sign * String(a).localeCompare(String(b), undefined, { sensitivity: "base" });
    }
    return sign * (Number(a) - Number(b));
  });
}

/** A new column opens at the end people look at first; the same column flips. */
export function nextSort(current: Sort | null, key: SortKey): Sort {
  if (current?.key === key) {
    return { key, direction: current.direction === "desc" ? "asc" : "desc" };
  }
  return { key, direction: "desc" };
}
