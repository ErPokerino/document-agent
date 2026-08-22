import type { Evaluation } from "./types";

export type SortKey =
  | "status"
  | "id"
  | "created_at"
  | "model"
  | "total_documents"
  | "total_elapsed_ms"
  | "max_pages"
  | "accuracy";

export type SortDirection = "asc" | "desc";
export type Sort = { key: SortKey; direction: SortDirection };

const TEXT_KEYS: SortKey[] = ["status", "model", "created_at"];

function value(evaluation: Evaluation, key: SortKey): number | string | null {
  if (key === "accuracy") return evaluation.metrics.accuracy;
  return evaluation[key];
}

export function sortEvaluations(
  evaluations: Evaluation[],
  key: SortKey,
  direction: SortDirection,
): Evaluation[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...evaluations].sort((left, right) => {
    const a = value(left, key);
    const b = value(right, key);

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
