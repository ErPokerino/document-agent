"use client";

import { LoaderCircle, Square, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { formatUsd } from "../lib/cost";
import {
  VERDICT_LABELS,
  cellAt,
  cellName,
  finishedCells,
  gridColumns,
  gridRows,
  interval,
  runnableCells,
  signedPoints,
} from "../lib/experiments";
import { accuracyClass, percent } from "../lib/format";
import { InfoHint } from "./info-hint";
import type { Evaluation, Experiment, ExperimentCellScore } from "../lib/types";

type Props = {
  experiments: Experiment[];
  selected: number | null;
  onSelect: (id: number | null) => void;
  onOpenRun: (evaluationId: number) => void;
  onChanged: () => Promise<void>;
  costOf: (evaluation: Evaluation) => number | null;
  onError: (message: string) => void;
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Waiting",
  loading: "Loading model",
  running: "Running",
  completed: "Done",
  partial: "Partial",
  failed: "Failed",
  cancelled: "Cancelled",
  skipped: "Skipped",
  error: "Did not start",
};

/** Every experiment, and the one open as a grid with its paired comparison. */
export function ExperimentsView({ experiments, selected, onSelect, onOpenRun, onChanged, costOf, onError }: Props) {
  const [detail, setDetail] = useState<Experiment | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const current = experiments.find((experiment) => experiment.id === selected) ?? null;
  const running = current?.status === "running";
  const finished = current ? finishedCells(current) : 0;

  useEffect(() => {
    if (selected === null) return;
    let active = true;
    const load = () => api.experiment(selected).then((next) => { if (active) setDetail(next); }).catch((cause) => onError(cause instanceof Error ? cause.message : String(cause)));
    void load();
    // While cells run, the grid fills in; once it stops, one read is enough.
    const timer = running ? window.setInterval(() => { void load(); }, 2000) : undefined;
    return () => { active = false; if (timer) window.clearInterval(timer); };
  }, [selected, running, finished, onError]);

  if (!experiments.length) {
    return <p className="field-help">No experiment yet. Choose <strong>Experiment</strong> above to compare several pipelines and models on one dataset.</p>;
  }

  const shown = detail && detail.id === selected ? detail : null;

  return (
    <div className="experiments">
      <div className="experiment-list">
        {experiments.map((experiment) => (
          <button
            key={experiment.id}
            className={`experiment-item ${experiment.id === selected ? "active" : ""}`}
            onClick={() => onSelect(experiment.id === selected ? null : experiment.id)}
          >
            <strong>{experiment.name}</strong>
            <small>{experiment.dataset} · {finishedCells(experiment)}/{runnableCells(experiment)} cells · {experiment.created_at.slice(0, 16).replace("T", " ")}</small>
            <span className={`status-tag ${experiment.status}`}>{experiment.status}</span>
          </button>
        ))}
      </div>

      {shown && (
        <div className="experiment-detail">
          <div className="experiment-detail-head">
            <div>
              <h4>{shown.name}</h4>
              <p className="field-help">
                {shown.dataset} · {finishedCells(shown)} of {runnableCells(shown)} cells finished
                {shown.reuse_readings ? " · stored readings reused, so time and cost are not what the pipelines cost" : ""}
              </p>
            </div>
            {shown.status === "running" ? (
              <button className="secondary-button small" onClick={() => void api.cancelExperiment(shown.id).then(onChanged).catch((cause) => onError(String(cause)))}>
                <Square size={13} /> Cancel
              </button>
            ) : confirmingDelete ? (
              <span className="artifact-actions">
                <small>The runs stay in Past runs.</small>
                <button className="secondary-button small" onClick={() => setConfirmingDelete(false)}>Keep</button>
                <button className="secondary-button small danger" onClick={() => void api.deleteExperiment(shown.id).then(async () => { setConfirmingDelete(false); onSelect(null); await onChanged(); }).catch((cause) => onError(String(cause)))}>Delete</button>
              </span>
            ) : (
              <button className="icon-button" aria-label="Delete experiment" title="Delete the experiment; its runs stay in Past runs" onClick={() => setConfirmingDelete(true)}><Trash2 size={15} /></button>
            )}
            <button className="icon-button" aria-label="Close experiment" onClick={() => onSelect(null)}><X size={15} /></button>
          </div>
          {shown.error && <p className="field-warning">{shown.error}</p>}

          <ExperimentGrid experiment={shown} onOpenRun={onOpenRun} costOf={costOf} />
          <Comparison experiment={shown} costOf={costOf} onOpenRun={onOpenRun} />
        </div>
      )}
    </div>
  );
}

function scoreOf(experiment: Experiment, index: number): ExperimentCellScore | undefined {
  return experiment.comparison?.cells.find((score) => score.cell === index);
}

function perDocumentCost(run: Evaluation | null, costOf: (evaluation: Evaluation) => number | null): number | null {
  if (!run || run.cached_pages) return null;
  const cost = costOf(run);
  const documents = run.succeeded_documents || 0;
  return cost === null || !documents ? null : cost / documents;
}

function ExperimentGrid({ experiment, onOpenRun, costOf }: { experiment: Experiment; onOpenRun: (id: number) => void; costOf: (evaluation: Evaluation) => number | null }) {
  const columns = gridColumns(experiment);
  return (
    <div className="confusion-scroll">
      <table className="experiment-grid">
        <thead>
          <tr>
            <th aria-label="Pipeline" />
            {columns.map((column) => <th key={column.key}>{column.label}<small>{column.provider === "gemini" ? "hosted" : column.provider === "lm_studio" ? "local" : ""}</small></th>)}
          </tr>
        </thead>
        <tbody>
          {gridRows(experiment).map((pipeline) => (
            <tr key={pipeline}>
              <th>{pipeline}</th>
              {columns.map((column) => {
                const cell = cellAt(experiment, pipeline, column.key);
                if (!cell) return <td key={column.key} className="empty" />;
                const score = scoreOf(experiment, cell.index);
                const cost = perDocumentCost(cell.run, costOf);
                const accuracy = score?.accuracy ?? cell.run?.metrics.accuracy ?? null;
                return (
                  <td key={column.key} className={`result ${cell.status} ${score?.verdict ?? ""}`}>
                    {cell.run ? (
                      <button className="experiment-cell" onClick={() => onOpenRun(cell.run!.id)} title="Open this run">
                        <strong className={accuracyClass(accuracy)}>{percent(accuracy)}</strong>
                        {score && <small>{interval(score)}</small>}
                        <span>
                          {cell.run.average_elapsed_ms ? `${(cell.run.average_elapsed_ms / 1000).toFixed(1)} s/doc` : ""}
                          {cost !== null ? ` · ${formatUsd(cost)}/doc` : ""}
                        </span>
                        {score && score.verdict !== "worse" && <em>{score.verdict === "best" ? "Best" : "≈ best"}</em>}
                        {["running", "loading"].includes(cell.status) && <em><LoaderCircle className="spin" size={11} /> {STATUS_LABELS[cell.status]}</em>}
                        {["partial", "failed", "cancelled"].includes(cell.status) && <em>{STATUS_LABELS[cell.status]}</em>}
                      </button>
                    ) : (
                      <span className="experiment-cell idle" title={cell.skipped ?? cell.error ?? undefined}>
                        {["loading", "running"].includes(cell.status) && <LoaderCircle className="spin" size={12} />} {STATUS_LABELS[cell.status] ?? cell.status}
                        {(cell.skipped || cell.error) && <small>{cell.skipped ?? cell.error}</small>}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Comparison({ experiment, costOf, onOpenRun }: { experiment: Experiment; costOf: (evaluation: Evaluation) => number | null; onOpenRun: (id: number) => void }) {
  const comparison = experiment.comparison;
  if (!comparison) return <p className="field-help">The comparison appears once a cell has scored a document.</p>;
  if (!comparison.shared_documents.length) {
    return <p className="field-help">No document was scored by every finished cell, so nothing can be compared on the same documents.</p>;
  }
  const fields = [...new Set(comparison.cells.flatMap((score) => Object.keys(score.per_entity)))].sort();
  return (
    <div className="experiment-comparison">
      <h4>
        Compared on the {comparison.shared_documents.length} documents every finished cell scored
        <InfoHint text={`Accuracy is pooled over the fields of those documents. The interval is a 95% bootstrap over documents (${comparison.resamples} resamples, fixed seed). The difference from the best is resampled on the same documents for both cells, so "not distinguishable" means these documents cannot tell the two apart — not that they are equal.`} />
      </h4>
      {comparison.left_out.length > 0 && (
        <p className="field-help">Left out because some finished cell did not score them: {comparison.left_out.join(", ")}.</p>
      )}
      <div className="confusion-scroll">
        <table className="classification-table">
          <thead>
            <tr><th>#</th><th>Configuration</th><th>Accuracy</th><th>95% interval</th><th>Difference from the best</th><th>Verdict</th><th>s/doc</th><th>Cost/doc</th></tr>
          </thead>
          <tbody>
            {comparison.cells.map((score, rank) => {
              const cell = experiment.cells[score.cell];
              const cost = perDocumentCost(cell.run, costOf);
              return (
                <tr key={score.cell} className={`verdict-${score.verdict}`}>
                  <td>{rank + 1}</td>
                  <td>{cell.run ? <button className="link-button" onClick={() => onOpenRun(cell.run!.id)}>{cellName(cell)}</button> : cellName(cell)}</td>
                  <td><strong>{percent(score.accuracy)}</strong></td>
                  <td>{interval(score)}</td>
                  <td>{score.verdict === "best" ? "—" : `${signedPoints(score.delta)} (${signedPoints(score.delta_low)} to ${signedPoints(score.delta_high)})`}</td>
                  <td>{VERDICT_LABELS[score.verdict]}</td>
                  <td>{score.seconds_per_document === null || experiment.reuse_readings ? "—" : score.seconds_per_document.toFixed(1)}</td>
                  <td>{cost === null ? "—" : formatUsd(cost)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {fields.length > 1 && (
        <>
          <h4>Per field, on the same documents</h4>
          <div className="confusion-scroll">
            <table className="classification-table">
              <thead>
                <tr><th>Field</th>{comparison.cells.map((score) => <th key={score.cell}>{cellName(experiment.cells[score.cell])}</th>)}</tr>
              </thead>
              <tbody>
                {fields.map((field) => {
                  const values = comparison.cells.map((score) => score.per_entity[field] ?? null);
                  const top = Math.max(...values.map((value) => value ?? -1));
                  return (
                    <tr key={field}>
                      <td><code>{field}</code></td>
                      {values.map((value, position) => (
                        <td key={position} className={value !== null && value === top ? "field-top" : ""}>{percent(value)}</td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
