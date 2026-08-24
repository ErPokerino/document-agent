import type { Evaluation } from "./types";

/**
 * The bench read as a whole: which approaches are worth their cost.
 *
 * A run is one measurement; an approach is a model on a pipeline, and it is
 * approaches that get compared. So every run of the same pair collapses into
 * one point, and every figure is per document — a total that is large only
 * because the dataset was large says nothing about the approach.
 */

export type Axis = "secondsPerDocument" | "costPerDocument" | "tokensPerDocument";

export type ApproachPoint = {
  key: string;
  model: string;
  pipeline: string;
  runs: number;
  accuracy: number;
  secondsPerDocument: number | null;
  costPerDocument: number | null;
  tokensPerDocument: number | null;
};

export type CostOf = (evaluation: Evaluation) => number | null | undefined;

export const AXES: { key: Axis; label: string; format: (value: number) => string }[] = [
  {
    key: "secondsPerDocument",
    label: "Seconds per document",
    // Zero is the origin of the axis, not a measurement, so it is not dressed
    // up with a decimal place it never had.
    format: (value) => (value ? (value >= 10 ? `${Math.round(value)} s` : `${value.toFixed(1)} s`) : "0"),
  },
  {
    key: "costPerDocument",
    label: "Cost per document",
    format: (value) =>
      value ? (value >= 0.01 ? `$${value.toFixed(3)}` : `$${value.toPrecision(2)}`) : "$0",
  },
  {
    key: "tokensPerDocument",
    label: "Tokens per document",
    format: (value) => (value ? Math.round(value).toLocaleString() : "0"),
  },
];

function mean(values: number[]): number | null {
  const usable = values.filter((value) => Number.isFinite(value));
  if (!usable.length) return null;
  return usable.reduce((total, value) => total + value, 0) / usable.length;
}

export function approachPoints(evaluations: Evaluation[], costOf: CostOf): ApproachPoint[] {
  const grouped = new Map<
    string,
    { model: string; pipeline: string; accuracy: number[]; seconds: number[]; cost: number[]; tokens: number[] }
  >();

  for (const evaluation of evaluations) {
    const accuracy = evaluation.metrics.accuracy;
    // A run that scored nothing is not an approach with zero accuracy. It is a
    // run that failed, and plotting it as a point would libel the approach.
    if (accuracy === null || accuracy === undefined) continue;

    const key = `${evaluation.model}\u0000${evaluation.pipeline}`;
    const group =
      grouped.get(key) ??
      { model: evaluation.model, pipeline: evaluation.pipeline, accuracy: [], seconds: [], cost: [], tokens: [] };

    group.accuracy.push(accuracy);
    if (evaluation.average_elapsed_ms) group.seconds.push(evaluation.average_elapsed_ms / 1000);

    const documents = evaluation.succeeded_documents || evaluation.total_documents || 0;
    if (documents) {
      const cost = costOf(evaluation);
      if (cost !== null && cost !== undefined) group.cost.push(cost / documents);
      const tokens = (evaluation.prompt_tokens ?? 0) + (evaluation.completion_tokens ?? 0);
      if (tokens) group.tokens.push(tokens / documents);
    }
    grouped.set(key, group);
  }

  return [...grouped.entries()]
    .map(([key, group]) => ({
      key,
      model: group.model,
      pipeline: group.pipeline,
      runs: group.accuracy.length,
      accuracy: mean(group.accuracy) as number,
      secondsPerDocument: mean(group.seconds),
      costPerDocument: mean(group.cost),
      tokensPerDocument: mean(group.tokens),
    }))
    .sort((a, b) => a.model.localeCompare(b.model) || a.pipeline.localeCompare(b.pipeline));
}

/**
 * The approaches nothing else beats outright, left to right.
 *
 * On this chart accuracy is to be maximised and the other axis minimised, so
 * an approach is off the frontier only when something else is at least as
 * accurate *and* at least as cheap, and strictly better at one of them. Ties
 * both survive: two ways of getting the same result for the same price are
 * both worth knowing about.
 */
export function paretoFrontier(points: ApproachPoint[], axis: Axis): ApproachPoint[] {
  const placeable = points.filter((point) => {
    const value = point[axis];
    return value !== null && value !== undefined && Number.isFinite(value);
  });

  return placeable
    .filter((candidate) =>
      !placeable.some((other) => {
        if (other === candidate) return false;
        const better =
          other.accuracy >= candidate.accuracy && (other[axis] as number) <= (candidate[axis] as number);
        const strictly =
          other.accuracy > candidate.accuracy || (other[axis] as number) < (candidate[axis] as number);
        return better && strictly;
      }),
    )
    // Drawing order: a line through the frontier has to go left to right.
    .sort((a, b) => (a[axis] as number) - (b[axis] as number));
}

export type FieldScore = {
  entity: string;
  matched: number;
  total: number;
  accuracy: number;
};

/**
 * Accuracy per field over everything in view, worst first.
 *
 * Pooled rather than averaged per run: a field scored ten times in one run and
 * twice in another should weigh what it actually was, and the worst field is
 * the one worth acting on, so it leads.
 */
export function fieldAccuracy(evaluations: Evaluation[]): FieldScore[] {
  const totals = new Map<string, { matched: number; total: number }>();
  for (const evaluation of evaluations) {
    for (const [entity, score] of Object.entries(evaluation.metrics.per_entity ?? {})) {
      if (!score || !score.total) continue;
      const running = totals.get(entity) ?? { matched: 0, total: 0 };
      totals.set(entity, {
        matched: running.matched + score.matched,
        total: running.total + score.total,
      });
    }
  }
  return [...totals.entries()]
    .map(([entity, score]) => ({ entity, ...score, accuracy: score.matched / score.total }))
    .sort((a, b) => a.accuracy - b.accuracy || a.entity.localeCompare(b.entity));
}
