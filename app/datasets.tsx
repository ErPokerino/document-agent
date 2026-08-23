"use client";

import {
  AlertCircle,
  Check,
  Database,
  Eye,
  FilterX,
  History,
  LoaderCircle,
  Pencil,
  Plus,
  Save,
  Tag,
  Trash2,
  UploadCloud,
  Wand2,
  X,
} from "lucide-react";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { filterByName } from "../lib/document-filter";
import { formatLabels, labelModes } from "../lib/format";
import { draftFromModel, draftToLabels, labelsToDraft, type LabelDraft, type LabelMode } from "../lib/labels";
import type { Dataset, DatasetDocument, EntityDefinition, ExtractionRun } from "../lib/types";
import { DocumentPreview, type PreviewTarget } from "./document-preview";

type Props = {
  savedEntities: EntityDefinition[];
  isModelReady: boolean;
};

/** Documents with known correct values: the yardstick a test run is measured against. */
export function Datasets({ savedEntities, isModelReady }: Props) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DatasetDocument[]>([]);
  const [newDatasetName, setNewDatasetName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  // Inline confirmation instead of window.confirm: a browser dialog steals
  // focus, cannot be styled, and reads as a script prompt rather than part
  // of the application.
  const [confirmingDataset, setConfirmingDataset] = useState<string | null>(null);
  const [confirmingDocument, setConfirmingDocument] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [documentQuery, setDocumentQuery] = useState("");
  const [labelling, setLabelling] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState<Record<string, LabelDraft>>({});
  const [labelHints, setLabelHints] = useState<Record<string, string>>({});
  const [drafting, setDrafting] = useState<string | null>(null);
  const [validatedRuns, setValidatedRuns] = useState<ExtractionRun[]>([]);
  const [pickedRuns, setPickedRuns] = useState<Set<number>>(new Set());
  const [preview, setPreview] = useState<PreviewTarget | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);

  const visibleDocuments = filterByName(documents, documentQuery);

  async function refreshDatasets() {
    setDatasets(await api.datasets());
  }

  async function refreshDocuments(dataset: string) {
    setDocuments(await api.datasetDocuments(dataset));
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [nextDatasets, nextRuns] = await Promise.all([api.datasets(), api.runs(true)]);
        if (!active) return;
        setDatasets(nextDatasets);
        setValidatedRuns(nextRuns);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedDataset) return;
    const dataset = selectedDataset;
    let active = true;
    async function load() {
      try {
        const next = await api.datasetDocuments(dataset);
        if (active) setDocuments(next);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [selectedDataset]);

  async function guard(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  function openLabels(document: string) {
    void guard(async () => {
      const current = await api.documentLabels(selectedDataset!, document);
      setLabelDraft(labelsToDraft(current.labels, savedEntities));
      setLabelHints({});
      setLabelling(document);
    });
  }

  function draftWithModel(document: string) {
    setDrafting(document);
    void guard(async () => {
      try {
        const proposal = await api.draftLabels(selectedDataset!, document);
        setLabelDraft(draftFromModel(proposal.labels, savedEntities));
        setLabelHints(proposal.confidence);
        setLabelling(document);
      } finally {
        setDrafting(null);
      }
    });
  }

  function saveLabels() {
    const { labels, errors } = draftToLabels(labelDraft, savedEntities);
    if (errors.length) {
      setError(errors.join(" "));
      return;
    }
    void guard(async () => {
      await api.saveDocumentLabels(selectedDataset!, labelling!, labels);
      await refreshDocuments(selectedDataset!);
      await refreshDatasets();
      setLabelling(null);
    });
  }

  function uploadFiles(files: FileList | File[]) {
    const pdfs = [...files].filter((file) => file.name.toLowerCase().endsWith(".pdf"));
    if (!selectedDataset || pdfs.length === 0) {
      if (pdfs.length === 0) setError("Only PDF documents can be added to a dataset.");
      return;
    }
    void guard(async () => {
      for (const file of pdfs) await api.addDatasetDocument(selectedDataset, file);
      await refreshDocuments(selectedDataset);
      await refreshDatasets();
    });
  }

  function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) uploadFiles(event.target.files);
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    uploadFiles(event.dataTransfer.files);
  }

  function togglePicked(runId: number) {
    setPickedRuns((current) => {
      const next = new Set(current);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  }

  function promotePicked() {
    if (!selectedDataset || pickedRuns.size === 0) return;
    void guard(async () => {
      await api.promoteRuns(selectedDataset, [...pickedRuns]);
      await refreshDocuments(selectedDataset);
      await refreshDatasets();
      setPickedRuns(new Set());
    });
  }

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Database size={19} />
        <div><h2>Datasets</h2><p>Documents with known correct values, used to measure a change.</p></div>
      </div>

      {error && (
        <div className="alert error-alert" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Close"><X size={15} /></button>
        </div>
      )}

      <div className="settings-card">
        <div className="settings-card-heading">
      <span className="settings-card-icon"><Database size={18} /></span>
      <div><h3>Test datasets</h3><p>Documents with known correct values, used to measure a prompt change.</p></div>
        </div>

        <div className="dataset-create">
      <input className="text-input" placeholder="New dataset name" value={newDatasetName} onChange={(event) => setNewDatasetName(event.target.value)} />
      <button className="secondary-button" disabled={!newDatasetName.trim() || busy} onClick={() => guard(async () => { await api.createDataset(newDatasetName.trim()); setNewDatasetName(""); await refreshDatasets(); })}>
        <Plus size={14} /> Create
      </button>
        </div>

        {datasets.length === 0 ? (
      <div className="models-empty"><AlertCircle size={18} /><span>No dataset yet. Create one, or drop PDFs and their JSON labels into backend/data/datasets/.</span></div>
        ) : (
      <div className="dataset-list">
        {datasets.map((dataset) => (
          <div key={dataset.name} className={`dataset-option ${selectedDataset === dataset.name ? "selected" : ""}`}>
            {renaming === dataset.name ? (
              <form
                className="dataset-rename"
                onSubmit={(event) => {
                  event.preventDefault();
                  const next = renameValue.trim();
                  if (!next || next === dataset.name) { setRenaming(null); return; }
                  void guard(async () => {
                    await api.renameDataset(dataset.name, next);
                    if (selectedDataset === dataset.name) setSelectedDataset(next);
                    setRenaming(null);
                    await refreshDatasets();
                  });
                }}
              >
                {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
                <input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} aria-label={`New name for ${dataset.name}`} />
                <button type="submit" className="secondary-button small" disabled={busy}><Check size={13} /> Save</button>
                <button type="button" className="secondary-button small ghost" onClick={() => setRenaming(null)}>Cancel</button>
              </form>
            ) : confirmingDataset === dataset.name ? (
              <div className="row-confirm">
                <span><strong>Delete {dataset.name}?</strong> Its documents and labels go with it.</span>
                <button className="secondary-button small ghost" onClick={() => setConfirmingDataset(null)}>Cancel</button>
                <button
                  className="secondary-button small danger"
                  disabled={busy}
                  onClick={() => guard(async () => {
                    await api.deleteDataset(dataset.name);
                    if (selectedDataset === dataset.name) {
                      setSelectedDataset(null);
                      setDocuments([]);
                      setLabelling(null);
                    }
                    setConfirmingDataset(null);
                    await refreshDatasets();
                  })}
                >
                  <Trash2 size={13} /> Delete
                </button>
              </div>
            ) : (
              <>
                <button className="dataset-pick" onClick={() => { setSelectedDataset(dataset.name); setLabelling(null); setPickedRuns(new Set()); }}>
                  <span className="radio">{selectedDataset === dataset.name && <span />}</span>
                  <span className="model-option-copy"><strong>{dataset.name}</strong><small>{dataset.document_count} documents · {dataset.labelled_count} labelled</small></span>
                </button>
                {dataset.labelled_count === 0 && <em className="warn">No ground truth</em>}
                <button className="icon-button" aria-label={`Rename dataset ${dataset.name}`} onClick={() => { setRenameValue(dataset.name); setRenaming(dataset.name); setConfirmingDataset(null); }}>
                  <Pencil size={14} />
                </button>
                <button className="icon-button" aria-label={`Delete dataset ${dataset.name}`} disabled={busy} onClick={() => { setConfirmingDataset(dataset.name); setRenaming(null); }}>
                  <Trash2 size={15} />
                </button>
              </>
            )}
          </div>
        ))}
      </div>
        )}
      </div>

      {selectedDataset && (
        <div className="settings-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon"><Tag size={18} /></span>
        <div><h3>{selectedDataset}</h3><p>A document is only scored on the entities you labelled.</p></div>
      </div>

      <div
        className={`dataset-drop ${dragging ? "dragging" : ""}`}
        onDragEnter={() => setDragging(true)}
        onDragLeave={() => setDragging(false)}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
      >
        <UploadCloud size={20} />
        <div>
          <strong>Drop PDFs here</strong>
          <small>Several at once is fine</small>
        </div>
        <button className="secondary-button small" onClick={() => uploadInput.current?.click()}>Browse</button>
      </div>
      <input ref={uploadInput} type="file" accept="application/pdf,.pdf" multiple onChange={handleUpload} hidden />

      {validatedRuns.length > 0 && (
        <div className="promote-panel">
          <div className="promote-head">
            <History size={15} />
            <span>Reuse documents you already reviewed</span>
            <button className="link-button" onClick={() => setPickedRuns(pickedRuns.size === validatedRuns.length ? new Set() : new Set(validatedRuns.map((run) => run.id)))}>
              {pickedRuns.size === validatedRuns.length ? "Clear all" : "Select all"}
            </button>
          </div>
          <div className="promote-list">
            {validatedRuns.map((run) => (
              <label className="promote-item" key={run.id}>
                <input type="checkbox" checked={pickedRuns.has(run.id)} onChange={() => togglePicked(run.id)} />
                <span className="promote-name">{run.filename}</span>
                <small>{run.created_at.replace("T", " ").slice(0, 16)} · {run.model}</small>
              </label>
            ))}
          </div>
          <button className="secondary-button" disabled={pickedRuns.size === 0 || busy} onClick={promotePicked}>
            <Plus size={14} /> Add {pickedRuns.size || ""} {pickedRuns.size === 1 ? "document" : "documents"}
          </button>
        </div>
      )}

      {documents.length > 1 && (
        <div className="name-filter">
          <input
            placeholder="Filter by file name"
            value={documentQuery}
            onChange={(event) => setDocumentQuery(event.target.value)}
            aria-label="Filter documents by file name"
          />
          <small>{visibleDocuments.length} of {documents.length}</small>
          {documentQuery && (
            <button className="secondary-button small ghost" onClick={() => setDocumentQuery("")}>
              <FilterX size={13} /> Clear
            </button>
          )}
        </div>
      )}

      {documents.length === 0 ? (
        <div className="models-empty"><AlertCircle size={18} /><span>This dataset is empty.</span></div>
      ) : visibleDocuments.length === 0 ? (
        <div className="models-empty"><AlertCircle size={18} /><span>No document matches &quot;{documentQuery}&quot;.</span></div>
      ) : (
        <div className="document-list">
          {visibleDocuments.map((document) => (
            <div className="document-row" key={document.name}>
              <div className="document-meta">
                <strong>{document.name}</strong>
                <small>
                  {document.labelled ? `${document.labelled_entities.length} labelled · ${document.label_source}` : "No ground truth"}
                  {document.label_error && ` · ${document.label_error}`}
                </small>
              </div>
              <span className={`label-pill ${document.labelled ? "ok" : "missing"}`}>{document.labelled ? <Check size={11} /> : <AlertCircle size={11} />}</span>
              <button className="icon-button" aria-label={`Preview ${document.name}`} title="Open the document" onClick={() => setPreview({ dataset: selectedDataset, document: document.name })}><Eye size={15} /></button>
              <button className="secondary-button small" disabled={!isModelReady || busy} title={isModelReady ? "Extract with the active model, then review the result" : "Load and warm up the model in LLM first"} onClick={() => draftWithModel(document.name)}>
                {drafting === document.name ? <LoaderCircle className="spin" size={13} /> : <Wand2 size={13} />} Draft
              </button>
              <button className="secondary-button small" onClick={() => openLabels(document.name)}>{document.labelled ? "Edit" : "Label"}</button>
              {confirmingDocument === document.name ? (
                <span className="row-confirm compact">
                  <button className="secondary-button small ghost" onClick={() => setConfirmingDocument(null)}>Cancel</button>
                  <button
                    className="secondary-button small danger"
                    disabled={busy}
                    onClick={() => guard(async () => {
                      await api.removeDatasetDocument(selectedDataset, document.name);
                      setConfirmingDocument(null);
                      await refreshDocuments(selectedDataset);
                      await refreshDatasets();
                    })}
                  >
                    Remove
                  </button>
                </span>
              ) : (
                <button className="icon-button" aria-label={`Remove ${document.name}`} title={document.labelled ? "Removes the document and its ground truth" : "Remove this document"} onClick={() => setConfirmingDocument(document.name)}><Trash2 size={15} /></button>
              )}
            </div>
          ))}
        </div>
      )}

      {labelling && (
        <div className="label-editor">
          <div className="label-editor-head">
            <strong>Ground truth · {labelling}</strong>
            <button className="secondary-button small" onClick={() => setPreview({ dataset: selectedDataset, document: labelling })}>
              <Eye size={13} /> View document
            </button>
            <button className="icon-button" aria-label="Close" onClick={() => setLabelling(null)}><X size={15} /></button>
          </div>
          {Object.keys(labelHints).length > 0 && (
            <p className="field-help draft-note">
              <Wand2 size={12} /> Prefilled by the model. Check every value: the confidence beside each field is the model&apos;s own guess, not a guarantee.
            </p>
          )}
          {savedEntities.map((entity) => {
            const entry = labelDraft[entity.name] ?? { mode: "skip" as LabelMode, text: "" };
            const hint = labelHints[entity.name];
            return (
              <div className="label-row" key={entity.name}>
                <div className="label-name">
                  <span>{entity.name}</span>
                  <small>{formatLabels[entity.format]}</small>
                </div>
                <select value={entry.mode} onChange={(event) => setLabelDraft({ ...labelDraft, [entity.name]: { ...entry, mode: event.target.value as LabelMode } })}>
                  {Object.entries(labelModes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <input disabled={entry.mode !== "value"} placeholder={entry.mode === "value" ? "Correct value" : "—"} value={entry.text} onChange={(event) => setLabelDraft({ ...labelDraft, [entity.name]: { mode: "value", text: event.target.value } })} />
                {hint ? <span className={`confidence-pill ${hint}`}><i /> {hint}</span> : <span />}
              </div>
            );
          })}
          <div className="label-editor-actions">
            <p className="field-help">Entities left as <em>Not labelled</em> are excluded from the score. <em>Absent in document</em> means the model must return nothing.</p>
            <button className="primary-button" disabled={busy} onClick={saveLabels}><Save size={14} /> Save ground truth</button>
          </div>
        </div>
      )}
        </div>
      )}
    

      <DocumentPreview target={preview} onClose={() => setPreview(null)} />
    </section>
  );
}
