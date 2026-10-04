"use client";

import { Database, Download, LayoutList, Table2, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { apiUrls } from "../../lib/api";
import { formatBytes, percent } from "../../lib/format";
import { leaderboard, provenance } from "../../lib/training";
import { InfoHint } from "../components/info-hint";
import type { ArtifactSummary } from "../../lib/types";

type Props = {
  artifacts: ArtifactSummary[];
  busy: boolean;
  onImport: (file: File) => void;
  onDelete: (artifact: ArtifactSummary) => void;
  onPipelines: () => void;
};

function f1(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toFixed(2);
}

/** The registry: every model as a card, or every model side by side per field. */
export function TrainedModels({ artifacts, busy, onImport, onDelete, onPipelines }: Props) {
  const [view, setView] = useState<"compare" | "list">("compare");
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const importInput = useRef<HTMLInputElement>(null);

  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon"><Database size={18} /></span>
        <div>
          <h3>Trained models<InfoHint text="A model is never changed once stored. Its id is a hash of its files and how it was trained, so a pipeline that names it and a Lab run that used it point at exactly this model." /></h3>
          <p>Use one in a pipeline with the <strong>Trained model</strong> step. Export carries a model to another machine.</p>
        </div>
        <div className="segmented lab-mode compact" role="tablist" aria-label="How to show the models">
          <button type="button" role="tab" aria-selected={view === "compare"} className={view === "compare" ? "active" : ""} onClick={() => setView("compare")}><Table2 size={13} /> Compare</button>
          <button type="button" role="tab" aria-selected={view === "list"} className={view === "list" ? "active" : ""} onClick={() => setView("list")}><LayoutList size={13} /> Details</button>
        </div>
        <button className="secondary-button small" disabled={busy} onClick={() => importInput.current?.click()}><Upload size={13} /> Import</button>
        <input
          ref={importInput}
          type="file"
          accept=".zip,application/zip"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) onImport(file);
          }}
        />
      </div>
      {artifacts.length === 0 && <p className="field-help">No model yet. Train one above, or import an exported one.</p>}

      {view === "compare" && artifacts.length > 0 && (
        <div className="model-leaderboard">
          <p className="field-help">
            Each field&apos;s models, best cross-validated accuracy first. These figures describe documents like the training ones;
            a Lab run or an experiment over a separate dataset measures new ones. Rows measured another way say so.
          </p>
          {leaderboard(artifacts).map((table) => (
            <div key={table.entity}>
              <h4><code>{table.entity}</code></h4>
              <div className="confusion-scroll">
                <table className="classification-table">
                  <thead>
                    <tr><th>#</th><th>Model</th><th>Algorithm</th><th>Features</th><th>Documents</th><th>Accuracy</th><th>Macro F1</th><th>Measured by</th></tr>
                  </thead>
                  <tbody>
                    {table.rows.map((row, rank) => (
                      <tr key={row.artifact.id} className={rank === 0 ? "verdict-best" : ""}>
                        <td>{rank + 1}</td>
                        <td>{row.artifact.name} <code>{row.artifact.id.slice(0, 8)}</code></td>
                        <td>{row.artifact.algorithm_label}</td>
                        <td>{row.artifact.features}{row.artifact.input_fields.length ? ` + ${row.artifact.input_fields.join(", ")}` : ""}</td>
                        <td>{row.documents ?? "—"}</td>
                        <td><strong>{percent(row.accuracy)}</strong></td>
                        <td>{f1(row.macroF1)}</td>
                        <td>{row.artifact.validation_method ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {view === "list" && (
        <div className="artifact-list">
          {artifacts.map((artifact) => (
            <div className="artifact-card" key={artifact.id}>
              <div className="artifact-head">
                <strong>{artifact.name}</strong>
                <code title={artifact.id}>{artifact.id.slice(0, 8)}</code>
                <span className="pages-tag">{artifact.algorithm_label}</span>
                {artifact.imported && <span className="pages-tag">Imported</span>}
                {!artifact.runnable && <span className="pages-tag">Cannot run here</span>}
                <span className="artifact-actions">
                  <a className="secondary-button small" href={apiUrls.artifactZip(artifact.id)} download><Download size={13} /> Export</a>
                  {confirmingDelete === artifact.id ? (
                    <>
                      <button className="secondary-button small" onClick={() => setConfirmingDelete(null)}>Keep</button>
                      <button className="secondary-button small danger" onClick={() => { setConfirmingDelete(null); onDelete(artifact); }}>Delete</button>
                    </>
                  ) : (
                    <button className="icon-button" aria-label={`Delete ${artifact.name}`} disabled={artifact.used_by.length > 0} title={artifact.used_by.length ? `Used by ${artifact.used_by.join(", ")}` : "Delete this model"} onClick={() => setConfirmingDelete(artifact.id)}><Trash2 size={15} /></button>
                  )}
                </span>
              </div>
              <p className="field-help">{provenance(artifact)} · {formatBytes(artifact.size_bytes)}</p>
              <p className="field-help">
                {artifact.features}
                {artifact.input_fields.length > 0 && ` · also reads ${artifact.input_fields.join(", ")}`}
                {Object.keys(artifact.hyperparameters).length > 0 && ` · ${Object.entries(artifact.hyperparameters).map(([key, value]) => `${key} ${value}`).join(", ")}`}
              </p>
              <table className="classification-table">
                <thead>
                  <tr>
                    <th>Field</th><th>Documents</th><th>Classes</th>
                    <th>Accuracy<InfoHint text={`${artifact.validation_method ?? "Validation"}: each training document predicted by a model that did not learn from it, copies of one file kept together. A measure of documents like these, not a Lab result.`} /></th>
                    <th>Macro F1</th>
                  </tr>
                </thead>
                <tbody>
                  {artifact.entities.map((name) => {
                    const measured = artifact.validation[name];
                    return (
                      <tr key={name}>
                        <td>{name}</td>
                        <td>{measured?.documents ?? "—"}</td>
                        <td>{measured?.classes ?? "—"}</td>
                        <td>{percent(measured?.accuracy)}</td>
                        <td>{f1(measured?.macro_f1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {artifact.used_by.length > 0 && (
                <p className="field-help">Used by <button type="button" className="link-button" onClick={onPipelines}>{artifact.used_by.join(", ")}</button></p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
