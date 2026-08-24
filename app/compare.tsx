"use client";

import { BarChart3 } from "lucide-react";
import { useState } from "react";

import { accuracyClass, percent } from "../lib/format";
import {
  METRICS,
  buildPivot,
  cellKey,
  entityBreakdown,
  type CostOf,
  type PivotMetricKey,
} from "../lib/run-pivot";
import type { Evaluation } from "../lib/types";
import { InfoHint } from "./info-hint";

type Props = {
  evaluations: Evaluation[];
  costOf: CostOf;
};

/**
 * The runs held against each other, rather than read one at a time.
 *
 * Everything here comes from the runs already on screen, so the filters above
 * decide what is compared. Nothing is stored and nothing is recomputed on the
 * backend: a rate edited in LLM moves the cost column here immediately, for
 * the same reason it moves it in the table.
 */
export function CompareRuns({ evaluations, costOf }: Props) {
  const [metricKey, setMetricKey] = useState<PivotMetricKey>("accuracy");
  const pivot = buildPivot(evaluations, metricKey, costOf);
  const breakdown = entityBreakdown(evaluations);
  const datasets = new Set(evaluations.map((evaluation) => evaluation.dataset));

  if (pivot.rows.length === 0) {
    return (
      <div className="settings-card">
        <div className="settings-card-heading">
          <div><h3>Compare</h3><p>Approaches held against each other, over the runs selected above.</p></div>
        </div>
        <div className="models-empty"><BarChart3 size={18} /><span>No run in the current selection has a score to compare.</span></div>
      </div>
    );
  }

  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <div>
          <h3>Compare<InfoHint text="Built from the runs the filters above leave in view. Every figure is per document, so runs over datasets of different sizes still compare. A cell holding several runs shows their mean." /></h3>
          <p>Each model against each pipeline. {pivot.best && <>Best {pivot.metric.label.toLowerCase()}: <strong>{pivot.best.row}</strong> on <strong>{pivot.best.column}</strong>.</>}</p>
        </div>
        <select className="compare-metric" value={metricKey} onChange={(event) => setMetricKey(event.target.value as PivotMetricKey)} aria-label="Metric to compare">
          {METRICS.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
        </select>
      </div>

      {datasets.size > 1 && (
        <p className="compare-caution">
          These runs span {datasets.size} datasets. Accuracy on one says nothing about accuracy on another — narrow the Dataset filter above to compare like with like.
        </p>
      )}

      <div className="runs-table-wrap">
        <table className="runs-table compare-table">
          <thead>
            <tr>
              <th>Model</th>
              {pivot.columns.map((column) => <th key={column} className="numeric">{column}</th>)}
            </tr>
          </thead>
          <tbody>
            {pivot.rows.map((row) => (
              <tr key={row}>
                <td className="compare-row-label">{row}</td>
                {pivot.columns.map((column) => {
                  const cell = pivot.cells.get(cellKey(row, column));
                  const isBest = pivot.best?.row === row && pivot.best?.column === column;
                  return (
                    <td key={column} className={`numeric compare-cell ${isBest ? "best" : ""} ${cell ? "" : "empty"}`}>
                      {cell ? (
                        <>
                          <strong className={metricKey === "accuracy" ? accuracyClass(cell.value) : ""}>{pivot.metric.format(cell.value)}</strong>
                          {cell.runs > 1 && <small>mean of {cell.runs}</small>}
                        </>
                      ) : (
                        <span className="compare-none" title="Never run">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {breakdown.entities.length > 0 && (
        <>
          <h4 className="compare-subheading">
            Where the errors are
            <InfoHint text="Accuracy per field, for each approach. The headline number says an approach lost three fields out of sixty; this says which three, which is the difference between changing model and fixing one field." />
          </h4>
          <div className="runs-table-wrap">
            <table className="runs-table compare-table">
              <thead>
                <tr>
                  <th>Approach</th>
                  {breakdown.entities.map((entity) => <th key={entity} className="numeric">{entity}</th>)}
                </tr>
              </thead>
              <tbody>
                {breakdown.approaches.map((approach) => (
                  <tr key={`${approach.model}-${approach.pipeline}`}>
                    <td className="compare-row-label">
                      <strong>{approach.model}</strong>
                      <small>{approach.pipeline}{approach.runs > 1 ? ` · ${approach.runs} runs` : ""}</small>
                    </td>
                    {breakdown.entities.map((entity) => {
                      const score = approach.byEntity.get(entity);
                      return (
                        <td key={entity} className="numeric compare-cell">
                          {score === undefined
                            ? <span className="compare-none" title="Not scored">—</span>
                            : <strong className={accuracyClass(score)}>{percent(score)}</strong>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
