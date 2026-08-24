import type { Evaluation } from "./types";

/**
 * Comparing approaches, rather than reading runs one at a time.
 *
 * Past runs is a list, and a list answers "what happened". The question this
 * bench is actually for is "which approach is better, and at what cost" —
 * which means holding one model against another across the same pipelines.
 * That is a matrix, so this builds one.
 *
 * Every number here is per document. Runs over datasets of different sizes are
 * otherwise incomparable, and a total that is large because the dataset was
 * large says nothing about the approach.
 */

export type PivotMetricKey =
  | "accuracy"
  | "seconds_per_document"
  | "cost_per_document"
  | "tokens_per_document";

export type PivotMetric = {
  key: PivotMetricKey;
  label: string;
  /** Which direction wins. Fastest and cheapest are not the largest number. */
  higherIsBetter: boolean;
  format: (value: number) => string;
};

export const METRICS: PivotMetric[] = [
  {
    key: "accuracy",
    label: "Accuracy",
    higherIsBetter: true,
    format: (value) => `${Math.round(value * 100)}%`,
  },
  {
    key: "seconds_per_document",
    label: "Seconds per document",
    higherIsBetter: false,
    format: (value) => `${value.toFixed(1)} s`,
  },
  {
    key: "cost_per_document",
    label: "Cost per document",
    higherIsBetter: false,
    format: (value) => (value >= 0.01 ? `$${value.toFixed(3)}` : `$${value.toPrecision(2)}`),
  },
  {
    key: "tokens_per_document",
    label: "Tokens per document",
    higherIsBetter: false,
    format: (value) => Math.round(value).toLocaleString(),
  },
];

export type PivotCell = {
  value: number;
  /** How many runs are behind the number, which is worth knowing before trusting it. */
  runs: number;
};

export type Pivot = {
  rows: string[];
  columns: string[];
  cells: Map<string, PivotCell>;
  best: { row: string; column: string; value: number } | null;
  metric: PivotMetric;
};

export type CostOf = (evaluation: Evaluation) => number | null | undefined;

/** Models and pipelines are free text, so the pair needs a separator neither uses. */
export function cellKey(row: string, column: string): string {
  return `${row}\u0000${column}`;
}

function documentsIn(evaluation: Evaluation): number {
  // What was actually scored, not what was queued: a run that stopped part way
  // through must not look cheap per document because of the ones it skipped.
  return evaluation.succeeded_documents || evaluation.total_documents || 0;
}

function measure(
  evaluation: Evaluation,
  metric: PivotMetricKey,
  costOf: CostOf,
): number | null {
  const documents = documentsIn(evaluation);
  if (metric === "accuracy") return evaluation.metrics.accuracy;
  if (metric === "seconds_per_document") {
    const average = evaluation.average_elapsed_ms;
    return average === null || average === undefined ? null : average / 1000;
  }
  if (!documents) return null;
  if (metric === "cost_per_document") {
    const cost = costOf(evaluation);
    return cost === null || cost === undefined ? null : cost / documents;
  }
  const tokens = (evaluation.prompt_tokens ?? 0) + (evaluation.completion_tokens ?? 0);
  return tokens ? tokens / documents : null;
}

export function buildPivot(
  evaluations: Evaluation[],
  metricKey: PivotMetricKey,
  costOf: CostOf,
): Pivot {
  const metric = METRICS.find((candidate) => candidate.key === metricKey) ?? METRICS[0];
  const totals = new Map<string, { sum: number; runs: number }>();
  const rows = new Set<string>();
  const columns = new Set<string>();

  for (const evaluation of evaluations) {
    const value = measure(evaluation, metric.key, costOf);
    // A run with nothing to report is not a zero. Counting it would drag an
    // average down and make a failed run look like a bad approach.
    if (value === null || !Number.isFinite(value)) continue;
    rows.add(evaluation.model);
    columns.add(evaluation.pipeline);
    const key = cellKey(evaluation.model, evaluation.pipeline);
    const running = totals.get(key) ?? { sum: 0, runs: 0 };
    totals.set(key, { sum: running.sum + value, runs: running.runs + 1 });
  }

  const cells = new Map<string, PivotCell>();
  let best: Pivot["best"] = null;
  for (const [key, { sum, runs }] of totals) {
    const value = sum / runs;
    cells.set(key, { value, runs });
    if (best === null || (metric.higherIsBetter ? value > best.value : value < best.value)) {
      const [row, column] = key.split("\u0000");
      best = { row, column, value };
    }
  }

  return {
    rows: [...rows].sort((a, b) => a.localeCompare(b)),
    columns: [...columns].sort((a, b) => a.localeCompare(b)),
    cells,
    best,
    metric,
  };
}

export type EntityBreakdown = {
  entities: string[];
  approaches: {
    model: string;
    pipeline: string;
    runs: number;
    byEntity: Map<string, number>;
  }[];
};

/**
 * Per-field accuracy for each approach.
 *
 * The headline number says an approach lost three fields out of sixty. This
 * says which three, which is the difference between "try another model" and
 * "supplier_name needs a register lookup".
 */
export function entityBreakdown(evaluations: Evaluation[]): EntityBreakdown {
  const entities = new Set<string>();
  const grouped = new Map<
    string,
    { model: string; pipeline: string; runs: number; totals: Map<string, { matched: number; total: number }> }
  >();

  for (const evaluation of evaluations) {
    const perEntity = evaluation.metrics.per_entity ?? {};
    const key = cellKey(evaluation.model, evaluation.pipeline);
    const group =
      grouped.get(key) ??
      { model: evaluation.model, pipeline: evaluation.pipeline, runs: 0, totals: new Map() };
    let counted = false;
    for (const [entity, score] of Object.entries(perEntity)) {
      // An entity nothing was scored against says nothing about the approach.
      if (!score || !score.total) continue;
      counted = true;
      entities.add(entity);
      const running = group.totals.get(entity) ?? { matched: 0, total: 0 };
      group.totals.set(entity, {
        matched: running.matched + score.matched,
        total: running.total + score.total,
      });
    }
    if (counted) {
      group.runs += 1;
      grouped.set(key, group);
    }
  }

  return {
    entities: [...entities].sort((a, b) => a.localeCompare(b)),
    approaches: [...grouped.values()]
      .sort(
        (a, b) => a.model.localeCompare(b.model) || a.pipeline.localeCompare(b.pipeline),
      )
      .map((group) => ({
        model: group.model,
        pipeline: group.pipeline,
        runs: group.runs,
        byEntity: new Map(
          [...group.totals].map(([entity, score]) => [entity, score.matched / score.total]),
        ),
      })),
  };
}
