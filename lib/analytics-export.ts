/**
 * The Analytics charts as files.
 *
 * The picture is for a slide; the CSV is the same numbers a spreadsheet can
 * sort. Accuracy stays a fraction, the way the runs export does, so a percent
 * sign does not turn the column into text.
 */

import { AXES, type ApproachPoint, type Axis, type FieldScore } from "./analytics.ts";

const APPROACH_COLUMNS = [
  "rank",
  "extraction_engine",
  "pipeline",
  "dataset",
  "detail",
  "runs",
  "accuracy",
  "seconds_per_document",
  "cost_per_document",
  "tokens_per_document",
  "frontier_for",
  "on_pareto_frontier",
] as const;

function cell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function measure(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  return String(Math.round(value * 1e6) / 1e6);
}

/** Rank is the number drawn on the chart, which follows the list order. */
export function approachesToCsv(points: ApproachPoint[], frontier: ApproachPoint[], axis: Axis): string {
  const onFrontier = new Set(frontier.map((point) => point.key));
  const frontierFor = AXES.find((item) => item.key === axis)?.label ?? axis;
  const lines = [APPROACH_COLUMNS.join(",")];
  points.forEach((point, index) => {
    lines.push(
      [
        index + 1,
        point.model,
        point.pipeline,
        point.dataset ?? "",
        point.detail ?? "",
        point.runs,
        measure(point.accuracy),
        measure(point.secondsPerDocument),
        measure(point.costPerDocument),
        measure(point.tokensPerDocument),
        frontierFor,
        onFrontier.has(point.key) ? "yes" : "no",
      ]
        .map(cell)
        .join(","),
    );
  });
  return `${lines.join("\n")}\n`;
}

export function fieldsToCsv(fields: FieldScore[]): string {
  const lines = [["entity", "matched", "total", "accuracy"].join(",")];
  for (const field of fields) {
    lines.push([field.entity, field.matched, field.total, measure(field.accuracy)].map(cell).join(","));
  }
  return `${lines.join("\n")}\n`;
}

const BAR = { good: "#2e9d74", fair: "#d29338", poor: "#c2523f" };

function barColor(accuracy: number): string {
  if (accuracy >= 0.9) return BAR.good;
  if (accuracy >= 0.6) return BAR.fair;
  return BAR.poor;
}

function xml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

export type ChartPaint = { paper: string; ink: string; muted: string; track: string };

/**
 * The field bars as a standalone picture.
 *
 * Drawn from the scores rather than copied off the page, so the file does not
 * depend on how wide the card happened to be.
 */
export function fieldChartSvg(fields: FieldScore[], paint: ChartPaint): string {
  const width = 760;
  const row = 28;
  const height = 48 + fields.length * row + 12;
  const rows = fields.map((field, index) => {
    const y = 48 + index * row;
    const span = Math.max(field.accuracy * 420, 2);
    return [
      `<text x="16" y="${y + 14}" fill="${paint.ink}" font-family="ui-monospace, monospace" font-size="12">${xml(field.entity)}</text>`,
      `<rect x="200" y="${y}" width="420" height="16" rx="4" fill="${paint.track}" />`,
      `<rect x="200" y="${y}" width="${span}" height="16" rx="4" fill="${barColor(field.accuracy)}" />`,
      `<text x="636" y="${y + 13}" fill="${paint.ink}" font-family="ui-sans-serif, sans-serif" font-size="12" font-weight="700">${Math.round(field.accuracy * 100)}%</text>`,
      `<text x="680" y="${y + 13}" fill="${paint.muted}" font-family="ui-monospace, monospace" font-size="11">${field.matched}/${field.total}</text>`,
    ].join("");
  });
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">`,
    `<rect width="100%" height="100%" fill="${paint.paper}" />`,
    `<text x="16" y="28" fill="${paint.ink}" font-family="ui-sans-serif, sans-serif" font-size="16" font-weight="700">Accuracy by field</text>`,
    ...rows,
    `</svg>`,
  ].join("");
}
