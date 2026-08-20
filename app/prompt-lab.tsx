"use client";

import {
  AlertCircle,
  Braces,
  Check,
  CheckCircle2,
  Database,
  FilterX,
  FlaskConical,
  History,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Square,
  Tag,
  Trash2,
  UploadCloud,
  Wand2,
  X,
} from "lucide-react";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import {
  draftFromModel,
  draftToLabels,
  labelsToDraft,
  type LabelDraft,
  type LabelMode,
} from "../lib/labels";
import {
  distinctModels,
  emptyFilters,
  filterEvaluations,
  hasActiveFilters,
  type EvaluationFilters,
} from "../lib/run-filters";
import type {
  AppSettings,
  Dataset,
  DatasetDocument,
  EntityDefinition,
  EntityFormat,
  Evaluation,
  EvaluationDetail,
  ExtractionRun,
  MetricTally,
} from "../lib/types";

type LabTab = "prompts" | "datasets" | "runs";

const formatLabels: Record<EntityFormat, string> = {
  text: "Text",
  date: "Date · YYYY-MM-DD",
  currency: "Currency · ISO 4217",
  decimal: "Decimal number",
  integer: "Integer number",
};

const labelModes: Record<LabelMode, string> = {
  skip: "Not labelled",
  value: "Value",
  absent: "Absent in document",
};

function percent(accuracy: number | null | undefined) {
  return accuracy === null || accuracy === undefined ? "—" : `${Math.round(accuracy * 100)}%`;
}

function accuracyClass(accuracy: number | null | undefined) {
  if (accuracy === null || accuracy === undefined) return "";
  if (accuracy >= 0.9) return "good";
  if (accuracy >= 0.6) return "fair";
  return "poor";
}

function seconds(ms: number | null | undefined) {
  return ms === null || ms === undefined ? "—" : `${(ms / 1000).toFixed(1)} s`;
}

function describeValue(value: unknown) {
  return value === null || value === undefined ? "—" : String(value);
}

type Props = {
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
  savedEntities: EntityDefinition[];
  onSave: () => void;
  settingsState: "idle" | "saving" | "saved" | "error";
  settingsError: string | null;
  isModelReady: boolean;
};

export function PromptLab({
  draftSettings,
  setDraftSettings,
  savedEntities,
  onSave,
  settingsState,
  settingsError,
  isModelReady,
}: Props) {
  const [tab, setTab] = useState<LabTab>("prompts");
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
  const [confirmingRun, setConfirmingRun] = useState<number | null>(null);
  const [confirmingDocument, setConfirmingDocument] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [labelling, setLabelling] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState<Record<string, LabelDraft>>({});
  const [labelHints, setLabelHints] = useState<Record<string, string>>({});
  const [drafting, setDrafting] = useState<string | null>(null);
  const [validatedRuns, setValidatedRuns] = useState<ExtractionRun[]>([]);
  const [pickedRuns, setPickedRuns] = useState<Set<number>>(new Set());
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [openEvaluation, setOpenEvaluation] = useState<EvaluationDetail | null>(null);
  const [filters, setFilters] = useState<EvaluationFilters>(emptyFilters);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);

  const running = evaluations.find((evaluation) => evaluation.status === "running") ?? null;
  const visibleEvaluations = filterEvaluations(evaluations, filters);

  async function refreshDatasets() {
    setDatasets(await api.datasets());
  }

  async function refreshDocuments(dataset: string) {
    setDocuments(await api.datasetDocuments(dataset));
  }

  async function refreshEvaluations() {
    setEvaluations(await api.evaluations());
  }

  async function refreshValidatedRuns() {
    setValidatedRuns(await api.runs(true));
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [nextDatasets, nextEvaluations, nextRuns] = await Promise.all([
          api.datasets(),
          api.evaluations(),
          api.runs(true),
        ]);
        if (!active) return;
        setDatasets(nextDatasets);
        setEvaluations(nextEvaluations);
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

  // A test run is many model calls; poll while one is in flight.
  useEffect(() => {
    if (!running) return;
    const runningId = running.id;
    const openId = openEvaluation?.id;
    const timer = window.setInterval(() => {
      void api.evaluations().then(setEvaluations).catch(() => undefined);
      if (openId === runningId) {
        void api.evaluation(runningId).then(setOpenEvaluation).catch(() => undefined);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [running, openEvaluation?.id]);

  function openRun(evaluationId: number) {
    void guard(async () => setOpenEvaluation(await api.evaluation(evaluationId)));
  }

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

  function updateEntity(index: number, update: Partial<EntityDefinition>) {
    const entities = draftSettings.prompts.entities.map((entity, entityIndex) =>
      entityIndex === index ? { ...entity, ...update } : entity,
    );
    setDraftSettings({ ...draftSettings, prompts: { ...draftSettings.prompts, entities } });
  }

  function addEntity() {
    const existing = new Set(draftSettings.prompts.entities.map((entity) => entity.name));
    let suffix = 1;
    let name = "new_field";
    while (existing.has(name)) name = `new_field_${++suffix}`;
    setDraftSettings({
      ...draftSettings,
      prompts: {
        ...draftSettings.prompts,
        entities: [
          ...draftSettings.prompts.entities,
          { name, format: "text", description: "Describe where to find the value and how to interpret it." },
        ],
      },
    });
  }

  function removeEntity(index: number) {
    if (draftSettings.prompts.entities.length === 1) return;
    setDraftSettings({
      ...draftSettings,
      prompts: {
        ...draftSettings.prompts,
        entities: draftSettings.prompts.entities.filter((_, entityIndex) => entityIndex !== index),
      },
    });
  }

  function setPrompt(key: "system_prompt" | "user_prompt" | "confidence_prompt", value: string) {
    setDraftSettings({ ...draftSettings, prompts: { ...draftSettings.prompts, [key]: value } });
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

  const promptsTab = (
    <>
      <div className="settings-card prompt-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Sparkles size={18} /></span>
          <div><h3>Global prompts</h3><p>Control the agent, the single document request and the confidence rubric.</p></div>
        </div>
        <label className="input-label" htmlFor="system-prompt">System prompt</label>
        <textarea id="system-prompt" className="prompt-textarea large" value={draftSettings.prompts.system_prompt} onChange={(event) => setPrompt("system_prompt", event.target.value)} />
        <label className="input-label prompt-label" htmlFor="user-prompt">Extraction instructions</label>
        <textarea id="user-prompt" className="prompt-textarea" value={draftSettings.prompts.user_prompt} onChange={(event) => setPrompt("user_prompt", event.target.value)} />
        <p className="field-help">Use <code>{"{page_range}"}</code> to insert the pages included in the single model call.</p>
        <label className="input-label prompt-label" htmlFor="confidence-prompt">Confidence instructions</label>
        <textarea id="confidence-prompt" className="prompt-textarea" value={draftSettings.prompts.confidence_prompt} onChange={(event) => setPrompt("confidence_prompt", event.target.value)} />
        <p className="field-help">Define how the model assigns <code>low</code>, <code>medium</code> and <code>high</code> to every extracted value.</p>
      </div>

      <div className="settings-card entity-card">
        <div className="settings-card-heading entity-heading">
          <span className="settings-card-icon"><Braces size={18} /></span>
          <div><h3>Entities to extract</h3><p>Name, format and description automatically build the prompt and JSON Schema.</p></div>
          <button className="add-entity-button" onClick={addEntity}><Plus size={14} /> Add entity</button>
        </div>
        <div className="entity-list">
          {draftSettings.prompts.entities.map((entity, index) => (
            <div className="entity-editor" key={`${entity.name}-${index}`}>
              <div className="entity-index">{String(index + 1).padStart(2, "0")}</div>
              <div className="entity-fields">
                <div className="entity-row">
                  <label><span>JSON name</span><input value={entity.name} onChange={(event) => updateEntity(index, { name: event.target.value.toLowerCase().replaceAll(" ", "_") })} /></label>
                  <label><span>Format</span><select value={entity.format} onChange={(event) => updateEntity(index, { format: event.target.value as EntityFormat })}>{Object.entries(formatLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
                </div>
                <label className="entity-description"><span>Description for the model</span><textarea value={entity.description} onChange={(event) => updateEntity(index, { description: event.target.value })} /></label>
              </div>
              <button className="remove-entity-button" disabled={draftSettings.prompts.entities.length === 1} onClick={() => removeEntity(index)} aria-label={`Remove ${entity.name}`}><Trash2 size={15} /></button>
            </div>
          ))}
        </div>
      </div>
    </>
  );

  const datasetsTab = (
    <>
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

          {documents.length === 0 ? (
            <div className="models-empty"><AlertCircle size={18} /><span>This dataset is empty.</span></div>
          ) : (
            <div className="document-list">
              {documents.map((document) => (
                <div className="document-row" key={document.name}>
                  <div className="document-meta">
                    <strong>{document.name}</strong>
                    <small>
                      {document.labelled ? `${document.labelled_entities.length} labelled · ${document.label_source}` : "No ground truth"}
                      {document.label_error && ` · ${document.label_error}`}
                    </small>
                  </div>
                  <span className={`label-pill ${document.labelled ? "ok" : "missing"}`}>{document.labelled ? <Check size={11} /> : <AlertCircle size={11} />}</span>
                  <button className="secondary-button small" disabled={!isModelReady || busy} title={isModelReady ? "Extract with the active model, then review the result" : "Load and warm up the model in Settings first"} onClick={() => draftWithModel(document.name)}>
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
    </>
  );

  const tallyRows = (title: string, tallies: Record<string, MetricTally>) => (
    <div className="metric-block">
      <h4>{title}</h4>
      <div className="metric-rows">
        {Object.entries(tallies).map(([name, tally]) => (
          <div className="metric-row" key={name}>
            <span className="metric-name">{name}</span>
            <span className="metric-bar"><i className={accuracyClass(tally.accuracy)} style={{ width: `${(tally.accuracy ?? 0) * 100}%` }} /></span>
            <span className={`metric-value ${accuracyClass(tally.accuracy)}`}>{percent(tally.accuracy)}</span>
            <small>{tally.matched}/{tally.total}</small>
          </div>
        ))}
      </div>
    </div>
  );

  const runsTab = (
    <>
      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><FlaskConical size={18} /></span>
          <div><h3>Run a test</h3><p>Every labelled document in the dataset is extracted with the saved prompts and scored.</p></div>
        </div>

        <div className="run-controls">
          <select value={selectedDataset ?? ""} onChange={(event) => setSelectedDataset(event.target.value || null)}>
            <option value="">Choose a dataset…</option>
            {datasets.map((dataset) => <option key={dataset.name} value={dataset.name} disabled={dataset.labelled_count === 0}>{dataset.name} ({dataset.labelled_count} labelled)</option>)}
          </select>
          {running ? (
            <button className="secondary-button" onClick={() => guard(async () => { await api.cancelEvaluation(running.id); await refreshEvaluations(); })}>
              <Square size={14} /> Cancel
            </button>
          ) : (
            <button className="primary-button" disabled={!selectedDataset || busy || !isModelReady} onClick={() => guard(async () => { await api.startEvaluation(selectedDataset!); await refreshEvaluations(); await refreshValidatedRuns(); })}>
              <Play size={14} /> Run test
            </button>
          )}
        </div>
        {!isModelReady && <p className="field-help">Load and warm up the model in Settings before running a test.</p>}
        {running && (
          <div className="run-progress">
            <LoaderCircle className="spin" size={15} />
            <span>{running.dataset} · {running.completed_documents} of {running.total_documents} documents</span>
            <span className="run-progress-bar"><i style={{ width: `${(running.completed_documents / Math.max(running.total_documents, 1)) * 100}%` }} /></span>
          </div>
        )}
        <p className="field-help">A test uses the model, so document processing in Workspace is refused while it runs.</p>
      </div>

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><History size={18} /></span>
          <div><h3>Past runs</h3><p>Each run remembers the prompts, the model and the page limit it used.</p></div>
        </div>

        <div className="run-filters">
          <label><span>Model</span>
            <select value={filters.model} onChange={(event) => setFilters({ ...filters, model: event.target.value })}>
              <option value="">Any</option>
              {distinctModels(evaluations).map((model) => <option key={model} value={model}>{model}</option>)}
            </select>
          </label>
          <label><span>From</span>
            <input type="date" value={filters.since} onChange={(event) => setFilters({ ...filters, since: event.target.value })} />
          </label>
          <label><span>Min accuracy %</span>
            <input type="number" min="0" max="100" placeholder="Any" value={filters.minAccuracy} onChange={(event) => setFilters({ ...filters, minAccuracy: event.target.value })} />
          </label>
          <label><span>Min documents</span>
            <input type="number" min="0" placeholder="Any" value={filters.minDocuments} onChange={(event) => setFilters({ ...filters, minDocuments: event.target.value })} />
          </label>
          <button className="secondary-button small" disabled={!hasActiveFilters(filters)} onClick={() => setFilters(emptyFilters)}>
            <FilterX size={13} /> Clear
          </button>
        </div>

        {evaluations.length === 0 ? (
          <div className="models-empty"><AlertCircle size={18} /><span>No test has been run yet.</span></div>
        ) : visibleEvaluations.length === 0 ? (
          <div className="models-empty"><AlertCircle size={18} /><span>No run matches these filters. {evaluations.length} hidden.</span></div>
        ) : (
          <div className="runs-table-wrap">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Run</th>
                  <th>Date</th>
                  <th>Model</th>
                  <th className="numeric">Docs</th>
                  <th className="numeric">Total time</th>
                  <th className="numeric">Max pages</th>
                  <th className="numeric">Accuracy</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {visibleEvaluations.map((evaluation) => (
                  <tr
                    key={evaluation.id}
                    className={`${openEvaluation?.id === evaluation.id ? "selected" : ""} ${confirmingRun === evaluation.id ? "confirming" : ""}`}
                    tabIndex={0}
                    onClick={() => openRun(evaluation.id)}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      openRun(evaluation.id);
                    }}
                  >
                    <td><span className={`status-tag ${evaluation.status}`}>{evaluation.status}</span></td>
                    <td className="run-id">#{evaluation.id}<small>{evaluation.dataset}</small></td>
                    <td className="run-date">{evaluation.created_at.replace("T", " ").slice(0, 16)}</td>
                    <td><span className="model-tag">{evaluation.model}</span></td>
                    <td className="numeric">
                      {evaluation.succeeded_documents}/{evaluation.total_documents}
                      {evaluation.failed_documents > 0 && <small className="poor">{evaluation.failed_documents} failed</small>}
                    </td>
                    <td className="numeric">{seconds(evaluation.total_elapsed_ms)}<small>{seconds(evaluation.average_elapsed_ms)} avg</small></td>
                    <td className="numeric">{evaluation.max_pages || "—"}</td>
                    <td className={`numeric accuracy-cell ${accuracyClass(evaluation.metrics.accuracy)}`}>
                      {percent(evaluation.metrics.accuracy)}
                      <small>{evaluation.metrics.matched}/{evaluation.metrics.total}</small>
                    </td>
                    <td className="row-actions" onClick={(event) => event.stopPropagation()}>
                      {confirmingRun === evaluation.id ? (
                        <span className="row-confirm compact">
                          <button className="secondary-button small ghost" onClick={() => setConfirmingRun(null)}>Cancel</button>
                          <button
                            className="secondary-button small danger"
                            disabled={busy}
                            onClick={() => guard(async () => {
                              await api.deleteEvaluation(evaluation.id);
                              if (openEvaluation?.id === evaluation.id) setOpenEvaluation(null);
                              setConfirmingRun(null);
                              await refreshEvaluations();
                            })}
                          >
                            Delete
                          </button>
                        </span>
                      ) : (
                        <button
                          className="icon-button"
                          aria-label={`Delete run ${evaluation.id}`}
                          disabled={evaluation.status === "running" || busy}
                          title={evaluation.status === "running" ? "Cancel the run before deleting it" : "Delete this run"}
                          onClick={() => setConfirmingRun(evaluation.id)}
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openEvaluation && (
        <div className="settings-card">
          <div className="settings-card-heading">
            <span className="settings-card-icon"><CheckCircle2 size={18} /></span>
            <div>
              <h3>Run #{openEvaluation.id} · {openEvaluation.dataset}</h3>
              <p>{openEvaluation.succeeded_documents} of {openEvaluation.total_documents} documents scored · {seconds(openEvaluation.total_elapsed_ms)} in total · {seconds(openEvaluation.average_elapsed_ms)} per document</p>
            </div>
            <button className="icon-button" aria-label="Close" onClick={() => setOpenEvaluation(null)}><X size={15} /></button>
          </div>

          <div className="run-tags">
            <span className="model-tag">{openEvaluation.model}</span>
            <span className="pages-tag">{openEvaluation.max_pages || "?"} pages per extraction</span>
            <span className="pages-tag">{openEvaluation.prompts.entities.length} entities</span>
          </div>

          {openEvaluation.error && <div className="alert error-alert"><AlertCircle size={17} /><span>{openEvaluation.error}</span></div>}

          {openEvaluation.failed_documents + openEvaluation.pending_documents > 0 && (
            <div className="retry-banner">
              <AlertCircle size={17} />
              <span>
                <strong>
                  {openEvaluation.failed_documents > 0 && `${openEvaluation.failed_documents} failed`}
                  {openEvaluation.failed_documents > 0 && openEvaluation.pending_documents > 0 && ", "}
                  {openEvaluation.pending_documents > 0 && `${openEvaluation.pending_documents} never processed`}
                  .
                </strong>{" "}
                The accuracy above covers only the {openEvaluation.succeeded_documents} documents that were scored.
                A retry reuses this run&apos;s prompts, model and page limit, so the result stays one experiment.
              </span>
              <button
                className="secondary-button"
                disabled={busy || !!running || !isModelReady}
                title={running ? "Another run is in progress" : !isModelReady ? "Load and warm up the model in Settings first" : "Process the documents this run did not score"}
                onClick={() => guard(async () => {
                  await api.retryEvaluation(openEvaluation.id);
                  await refreshEvaluations();
                  setOpenEvaluation(await api.evaluation(openEvaluation.id));
                })}
              >
                <RefreshCw size={14} /> Retry {openEvaluation.failed_documents + openEvaluation.pending_documents} documents
              </button>
            </div>
          )}

          <div className="metric-grid">
            {tallyRows("Accuracy per entity", openEvaluation.metrics.per_entity)}
            {tallyRows("How often each confidence level was right", openEvaluation.metrics.per_confidence)}
          </div>

          <div className="document-results">
            {openEvaluation.documents.map((document) => (
              <div className="document-result" key={document.name}>
                <div className="document-result-head">
                  <strong>{document.name}</strong>
                  {document.status === "failed"
                    ? <span className="status-tag failed">failed</span>
                    : <small>{document.items.filter((item) => item.matched).length}/{document.items.length} correct{document.elapsed_ms ? ` · ${seconds(document.elapsed_ms)}` : ""}</small>}
                </div>
                {document.error && <p className="field-warning"><AlertCircle size={11} /> {document.error}</p>}
                {document.items.some((item) => !item.matched) && (
                  <table className="mismatch-table">
                    <thead>
                      <tr>
                        <th>Entity</th>
                        <th>Expected</th>
                        <th>Got</th>
                        <th>Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {document.items.filter((item) => !item.matched).map((item) => (
                        <tr key={item.entity}>
                          <td className="mismatch-entity">{item.entity}</td>
                          <td><code className="expected">{describeValue(item.expected)}</code></td>
                          <td><code className="actual">{describeValue(item.actual)}</code></td>
                          <td><span className={`confidence-pill ${item.confidence}`}><i /> {item.confidence}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <FlaskConical size={19} />
        <div><h2>Prompt Lab</h2><p>Define what to extract, then measure whether a change made it better or worse.</p></div>
      </div>

      <div className="settings-tabs" role="tablist">
        <button className={tab === "prompts" ? "active" : ""} onClick={() => setTab("prompts")}><Braces size={15} /> Prompts &amp; entities <span>{draftSettings.prompts.entities.length}</span></button>
        <button className={tab === "datasets" ? "active" : ""} onClick={() => setTab("datasets")}><Database size={15} /> Datasets <span>{datasets.length}</span></button>
        <button className={tab === "runs" ? "active" : ""} onClick={() => setTab("runs")}><FlaskConical size={15} /> Test runs <span>{evaluations.length}</span></button>
      </div>

      {(error || settingsError) && (
        <div className="alert error-alert" role="alert">
          <AlertCircle size={17} />
          <span>{error ?? settingsError}</span>
          <button onClick={() => setError(null)} aria-label="Close"><X size={15} /></button>
        </div>
      )}

      {tab === "prompts" ? promptsTab : tab === "datasets" ? datasetsTab : runsTab}

      {tab === "prompts" && (
        <div className="settings-actions sticky-actions">
          <p><FlaskConical size={14} /> Saved prompts are what a test run uses.</p>
          <button className="primary-button save-button" disabled={settingsState === "saving"} onClick={onSave}>
            {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
            {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save prompts"}
          </button>
        </div>
      )}
    </section>
  );
}
