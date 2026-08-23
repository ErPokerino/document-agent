/**
 * Scoring a run again without some of its fields.
 *
 * A pipeline that does not fill a derived entity scores zero on it, which is
 * the truth and also drowns out what the pipeline does do. Excluding the field
 * here answers "how did it do on the rest" without touching the stored run:
 * the per-entity tallies it already carries are enough to subtract from.
 */

import type { Evaluation, Metrics } from "./types";

export type Score = { matched: number; total: number; accuracy: number | null };

export function scoreWithout(metrics: Metrics, excluded: string[]): Score {
  const ignore = new Set(excluded);
  let matched = 0;
  let total = 0;
  for (const [entity, tally] of Object.entries(metrics.per_entity)) {
    if (ignore.has(entity)) continue;
    matched += tally.matched;
    total += tally.total;
  }
  // Nothing scored is not the same as nothing scored right.
  return { matched, total, accuracy: total === 0 ? null : matched / total };
}

/** Every entity any of these runs scored, so the same choice fits them all. */
export function entitiesIn(runs: Pick<Evaluation, "metrics">[]): string[] {
  const names = new Set<string>();
  for (const run of runs) {
    for (const entity of Object.keys(run.metrics.per_entity)) names.add(entity);
  }
  return [...names].sort();
}
