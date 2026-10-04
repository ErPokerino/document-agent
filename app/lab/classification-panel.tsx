"use client";

import { useState } from "react";

import { COVERAGE_PLOT, cellWeight, linePath, placeCoverage, thresholdLabel, type PlacedPoint } from "../../lib/classification-view";
import { percent } from "../../lib/format";
import { InfoHint } from "../components/info-hint";
import type { ClassificationResult } from "../../lib/types";

function ratio(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

/** A categorical field judged as a classifier: per class, confused with what, and at what coverage. */
export function ClassificationPanel({ report }: { report: ClassificationResult }) {
  return (
    <div className="classification-panel">
      <div className="classification-head">
        <h4>{report.entity}</h4>
        <span>{report.documents} documents</span>
        <span>Accuracy <strong>{percent(report.accuracy)}</strong></span>
        <span>
          Macro F1 <strong>{ratio(report.macro_f1)}</strong>
          <InfoHint text="The unweighted mean of each class's F1. Accuracy can be high while a rare class is never found; macro F1 cannot." />
        </span>
      </div>
      <div className="classification-grid">
        <ClassTable report={report} />
        <ConfusionMatrix report={report} />
        <CoverageCurve report={report} />
      </div>
    </div>
  );
}

function ClassTable({ report }: { report: ClassificationResult }) {
  return (
    <div>
      <h5>Per class</h5>
      <table className="classification-table">
        <thead>
          <tr><th>Class</th><th>Docs</th><th>Precision</th><th>Recall</th><th>F1</th></tr>
        </thead>
        <tbody>
          {report.classes.map((score) => (
            <tr key={score.label}>
              <td>{score.label}</td>
              <td>{score.support}</td>
              <td>{ratio(score.precision)}</td>
              <td>{ratio(score.recall)}</td>
              <td>{ratio(score.f1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConfusionMatrix({ report }: { report: ClassificationResult }) {
  const expectedCount = report.classes.length;
  return (
    <div>
      <h5>
        Confusion
        <InfoHint text="Rows are the labelled class, columns the class that came back. (none) as a column is an answer withheld; as a row, a document labelled with no class." />
      </h5>
      <div className="confusion-scroll">
        <table className="confusion-table">
          <thead>
            <tr><th aria-label="Labelled class" />{report.labels.map((label) => <th key={label} title={label}>{label}</th>)}</tr>
          </thead>
          <tbody>
            {report.confusion.slice(0, expectedCount).map((row, rowIndex) => (
              <tr key={report.labels[rowIndex]}>
                <th title={report.labels[rowIndex]}>{report.labels[rowIndex]}</th>
                {row.map((count, columnIndex) => (
                  <td
                    key={columnIndex}
                    className={rowIndex === columnIndex ? "diagonal" : count ? "off-diagonal" : ""}
                    style={{ "--weight": cellWeight(count, report.confusion) } as React.CSSProperties}
                    title={`${report.labels[rowIndex]} read as ${report.labels[columnIndex]}: ${count}`}
                  >
                    {count || ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CoverageCurve({ report }: { report: ClassificationResult }) {
  const [hovered, setHovered] = useState<PlacedPoint | null>(null);
  const points = placeCoverage(report.coverage);
  const plot = COVERAGE_PLOT;
  const bottom = plot.height - plot.bottom;
  const right = plot.width - plot.right;
  if (!points.length) {
    return <div><h5>Coverage and accuracy</h5><p className="field-help">Nothing was answered, so there is no curve.</p></div>;
  }
  return (
    <div>
      <h5>
        Coverage and accuracy
        <InfoHint text={report.ranked_by === "score"
          ? "Accepting only answers whose score is at least the threshold: how many documents pass (coverage) and how many of those are right (accuracy). The score is the step's own number, such as a similarity."
          : "No step gave every answer a score, so answers are ranked by their confidence band: three points at most, not a curve."} />
      </h5>
      <svg
        className="coverage-chart"
        viewBox={`0 0 ${plot.width} ${plot.height}`}
        role="img"
        aria-label={`Accuracy against coverage for ${report.entity}`}
        onMouseLeave={() => setHovered(null)}
      >
        {[0, 0.5, 1].map((tick) => {
          const y = plot.top + (1 - tick) * (bottom - plot.top);
          return (
            <g key={tick}>
              <line className="grid" x1={plot.left} x2={right} y1={y} y2={y} />
              <text className="tick" x={plot.left - 6} y={y + 3} textAnchor="end">{tick * 100}%</text>
            </g>
          );
        })}
        {[0, 0.5, 1].map((tick) => (
          <text key={tick} className="tick" x={plot.left + tick * (right - plot.left)} y={bottom + 14} textAnchor="middle">{tick * 100}%</text>
        ))}
        <text className="axis-title" x={(plot.left + right) / 2} y={plot.height - 2} textAnchor="middle">Coverage</text>
        <path className="curve" d={linePath(points)} />
        {points.map((point) => (
          <g key={point.threshold} onMouseEnter={() => setHovered(point)} onFocus={() => setHovered(point)} tabIndex={0}>
            <circle className="hit" cx={point.x} cy={point.y} r={10} />
            <circle className={`marker ${hovered === point ? "active" : ""}`} cx={point.x} cy={point.y} r={4} />
          </g>
        ))}
      </svg>
      <p className="coverage-readout" aria-live="polite">
        {hovered
          ? <>Score {thresholdLabel(hovered.threshold, report.ranked_by)}: <strong>{percent(hovered.coverage)}</strong> of documents pass, <strong>{percent(hovered.accuracy)}</strong> of them right ({hovered.answered} answers).</>
          : "Point at the curve to read a threshold."}
      </p>
      <details className="coverage-table">
        <summary>Table</summary>
        <table className="classification-table">
          <thead><tr><th>Threshold</th><th>Answers</th><th>Coverage</th><th>Accuracy</th></tr></thead>
          <tbody>
            {[...points].reverse().map((point) => (
              <tr key={point.threshold}>
                <td>{thresholdLabel(point.threshold, report.ranked_by)}</td>
                <td>{point.answered}</td>
                <td>{percent(point.coverage)}</td>
                <td>{percent(point.accuracy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
