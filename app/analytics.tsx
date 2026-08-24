"use client";

import { ArrowDown, ArrowUp, BarChart3 } from "lucide-react";
import { useState } from "react";

import {
  AXES,
  approachPoints,
  fieldAccuracy,
  paretoFrontier,
  type ApproachPoint,
  type Axis,
  type CostOf,
} from "../lib/analytics";
import { accuracyClass, percent } from "../lib/format";
import type { Evaluation } from "../lib/types";
import { InfoHint } from "./info-hint";

type Props = {
  evaluations: Evaluation[];
  costOf: CostOf;
};

type Column = "model" | "pipeline" | "runs" | "accuracy" | Axis;
type Sort = { key: Column; descending: boolean };

const PLOT = { width: 760, height: 340, left: 54, right: 128, top: 18, bottom: 40 };

/**
 * The bench read as a picture, on its own page.
 *
 * This used to sit under the runs table, which made the page enormous and
 * buried the thing worth looking at. It is a view of its own now, reading the
 * same filtered selection as the table it sits beside.
 */
export function Analytics({ evaluations, costOf }: Props) {
  const [axis, setAxis] = useState<Axis>("secondsPerDocument");
  const [sort, setSort] = useState<Sort>({ key: "accuracy", descending: true });

  const points = approachPoints(evaluations, costOf);
  const fields = fieldAccuracy(evaluations);
  const meta = AXES.find((candidate) => candidate.key === axis) ?? AXES[0];

  if (points.length === 0) {
    return (
      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><BarChart3 size={18} /></span>
          <div><h3>Analytics</h3><p>Approaches compared over the runs in view.</p></div>
        </div>
        <div className="models-empty">
          <BarChart3 size={18} />
          <span>No run in this selection has a score to plot. Widen the filters, or run a test.</span>
        </div>
      </div>
    );
  }

  return (
    <>
      <ParetoChart points={points} axis={axis} meta={meta} onAxis={setAxis} />
      <ApproachTable points={points} axis={axis} meta={meta} sort={sort} onSort={setSort} />
      <FieldChart fields={fields} approaches={points.length} />
    </>
  );
}

// -- accuracy against what it costs -------------------------------------------

function ParetoChart({
  points,
  axis,
  meta,
  onAxis,
}: {
  points: ApproachPoint[];
  axis: Axis;
  meta: (typeof AXES)[number];
  onAxis: (axis: Axis) => void;
}) {
  const placeable = points.filter((point) => {
    const value = point[axis];
    return value !== null && value !== undefined && Number.isFinite(value);
  });
  const frontier = paretoFrontier(points, axis);
  const frontierKeys = new Set(frontier.map((point) => point.key));

  const xs = placeable.map((point) => point[axis] as number);
  const ys = placeable.map((point) => point.accuracy);
  // Headroom, and never a zero-width axis when every point happens to tie.
  const xMax = Math.max(...xs, 0) * 1.08 || 1;
  const yLow = Math.max(0, Math.min(...ys, 1) - 0.08);
  const yHigh = Math.min(1, Math.max(...ys, 0) + 0.04);
  const ySpan = Math.max(yHigh - yLow, 0.02);

  const plotWidth = PLOT.width - PLOT.left - PLOT.right;
  const plotHeight = PLOT.height - PLOT.top - PLOT.bottom;
  const x = (value: number) => PLOT.left + (value / xMax) * plotWidth;
  const y = (value: number) => PLOT.top + plotHeight - ((value - yLow) / ySpan) * plotHeight;

  const gridY = [0, 0.25, 0.5, 0.75, 1]
    .map((fraction) => yLow + fraction * ySpan)
    .filter((value) => value <= 1.0001);

  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <div>
          <h3>
            Accuracy against cost
            <InfoHint text="One point per model and pipeline, averaged over every run of it in the current selection. The line joins the approaches nothing else beats outright: to leave it, something has to be both more accurate and cheaper on this axis." />
          </h3>
          <p>Up is better, left is cheaper. The line is the Pareto frontier — everything below and to the right of it is beaten by something on it.</p>
        </div>
        <select className="compare-metric" value={axis} onChange={(event) => onAxis(event.target.value as Axis)} aria-label="What to plot accuracy against">
          {AXES.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.label}</option>)}
        </select>
      </div>

      {placeable.length === 0 ? (
        <div className="models-empty"><BarChart3 size={18} /><span>No approach in view has a {meta.label.toLowerCase()} to plot.</span></div>
      ) : (
        <div className="chart-wrap">
          <svg
            viewBox={`0 0 ${PLOT.width} ${PLOT.height}`}
            className="pareto-chart"
            role="img"
            aria-label={`Accuracy against ${meta.label.toLowerCase()} for ${placeable.length} approaches`}
          >
            {gridY.map((value) => (
              <g key={value}>
                <line className="chart-grid" x1={PLOT.left} x2={PLOT.width - PLOT.right} y1={y(value)} y2={y(value)} />
                <text className="chart-tick" x={PLOT.left - 8} y={y(value) + 3} textAnchor="end">{Math.round(value * 100)}%</text>
              </g>
            ))}
            {[0, 0.5, 1].map((fraction) => (
              <text key={fraction} className="chart-tick" x={x(xMax * fraction)} y={PLOT.height - PLOT.bottom + 16} textAnchor="middle">
                {meta.format(xMax * fraction)}
              </text>
            ))}
            <line className="chart-axis" x1={PLOT.left} x2={PLOT.width - PLOT.right} y1={PLOT.top + plotHeight} y2={PLOT.top + plotHeight} />
            <text className="chart-axis-label" x={PLOT.left + plotWidth / 2} y={PLOT.height - 6} textAnchor="middle">{meta.label}</text>

            {frontier.length > 1 && (
              <polyline
                className="chart-frontier"
                points={frontier.map((point) => `${x(point[axis] as number)},${y(point.accuracy)}`).join(" ")}
              />
            )}

            {placeable.map((point) => {
              const onFrontier = frontierKeys.has(point.key);
              return (
                <g key={point.key} className={`chart-point ${onFrontier ? "frontier" : ""}`}>
                  <circle cx={x(point[axis] as number)} cy={y(point.accuracy)} r={onFrontier ? 6 : 4.5} />
                  <title>
                    {`${point.model} · ${point.pipeline}\n${percent(point.accuracy)} · ${meta.format(point[axis] as number)}${point.runs > 1 ? `\nmean of ${point.runs} runs` : ""}`}
                  </title>
                </g>
              );
            })}

            {frontier.map((point) => (
              <text
                key={`label-${point.key}`}
                className="chart-point-label"
                x={x(point[axis] as number) + 9}
                y={y(point.accuracy) + 3}
              >
                {point.model}
              </text>
            ))}
          </svg>
        </div>
      )}
    </div>
  );
}

// -- the same points as a table someone can sort ------------------------------

const COLUMNS: { key: Column; label: string; numeric: boolean }[] = [
  { key: "model", label: "Model", numeric: false },
  { key: "pipeline", label: "Pipeline", numeric: false },
  { key: "runs", label: "Runs", numeric: true },
  { key: "accuracy", label: "Accuracy", numeric: true },
];

function ApproachTable({
  points,
  axis,
  meta,
  sort,
  onSort,
}: {
  points: ApproachPoint[];
  axis: Axis;
  meta: (typeof AXES)[number];
  sort: Sort;
  onSort: (sort: Sort) => void;
}) {
  const columns = [...COLUMNS, { key: axis as Column, label: meta.label, numeric: true }];
  const sorted = [...points].sort((left, right) => {
    const a = left[sort.key as keyof ApproachPoint];
    const b = right[sort.key as keyof ApproachPoint];
    // Missing data sinks either way, so an approach with no cost recorded does
    // not take the top of the table for having nothing to compare.
    if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
    if (b === null || b === undefined) return -1;
    const direction = sort.descending ? -1 : 1;
    if (typeof a === "string" && typeof b === "string") {
      return direction * a.localeCompare(b, undefined, { sensitivity: "base" });
    }
    return direction * (Number(a) - Number(b));
  });

  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <div>
          <h3>Compare<InfoHint text="One row per model and pipeline. Every column sorts. The figures are per document and averaged over each run of that approach in the current selection." /></h3>
          <p>{points.length} approaches over the runs in view.</p>
        </div>
      </div>
      <div className="runs-table-wrap">
        <table className="runs-table compare-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={column.numeric ? "numeric" : ""}
                  aria-sort={sort.key === column.key ? (sort.descending ? "descending" : "ascending") : "none"}
                >
                  <button
                    type="button"
                    className="sort-button"
                    onClick={() => onSort({ key: column.key, descending: sort.key === column.key ? !sort.descending : true })}
                  >
                    {column.label}
                    {sort.key === column.key && (sort.descending ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((point) => (
              <tr key={point.key}>
                <td>{point.model}</td>
                <td>{point.pipeline}</td>
                <td className="numeric">{point.runs}</td>
                <td className="numeric"><strong className={accuracyClass(point.accuracy)}>{percent(point.accuracy)}</strong></td>
                <td className="numeric">
                  {point[axis] === null || point[axis] === undefined
                    ? <span className="compare-none">—</span>
                    : meta.format(point[axis] as number)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// -- which fields are actually failing ----------------------------------------

function FieldChart({
  fields,
  approaches,
}: {
  fields: ReturnType<typeof fieldAccuracy>;
  approaches: number;
}) {
  if (fields.length === 0) return null;
  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <div>
          <h3>Accuracy by field<InfoHint text="Every field scored across the runs in view, pooled rather than averaged per run. Narrow the filters above to one model or one pipeline to see that approach on its own." /></h3>
          <p>Worst first, over {approaches === 1 ? "one approach" : `${approaches} approaches`} in view.</p>
        </div>
      </div>
      <ul className="field-bars">
        {fields.map((field) => (
          <li key={field.entity}>
            <span className="field-bar-name">{field.entity}</span>
            <span className="field-bar-track">
              <span
                className={`field-bar-fill ${accuracyClass(field.accuracy)}`}
                style={{ width: `${Math.max(field.accuracy * 100, 1.5)}%` }}
              />
            </span>
            <span className="field-bar-value">
              <strong>{percent(field.accuracy)}</strong>
              <small>{field.matched}/{field.total}</small>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
