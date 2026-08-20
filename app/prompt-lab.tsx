"use client";

import {
  AlertCircle,
  Braces,
  Check,
  CheckCircle2,
  Database,
  FlaskConical,
  History,
  LoaderCircle,
  Play,
  Plus,
  Save,
  Sparkles,
  Square,
  Tag,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { draftToLabels, labelsToDraft, type LabelDraft, type LabelMode } from "../lib/labels";
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

function describeValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  return String(value);
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
  const [labelling, setLabelling] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState<Record<string, LabelDraft>>({});
  const [validatedRuns, setValidatedRuns] = useState<ExtractionRun[]>([]);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [openEvaluation, setOpenEvaluation] = useState<EvaluationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);

  const running = evaluations.find((evaluation) => evaluation.status === "running") ?? null;

  const refreshDatasets = useCallback(async () => {
    setDatasets(await api.datasets());
  }, []);

  const refreshDocuments = useCallback(async (dataset: string) => {
    setDocuments(await api.datasetDocuments(dataset));
  }, []);

  const refreshEvaluations = useCallback(async () => {
    setEvaluations(await api.evaluations());
  }, []);

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
    const timer = window.setInterval(() => {
      void refreshEvaluations().catch(() => undefined);
      if (openEvaluation?.id === running.id) {
        void api.evaluation(running.id).then(setOpenEvaluation).catch(() => undefined);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [running, openEvaluation?.id, refreshEvaluations]);

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

  async function openLabels(document: string) {
    await guard(async () => {
      const current = await api.documentLabels(selectedDataset!, document);
      setLabelDraft(labelsToDraft(current.labels, savedEntities));
      setLabelling(document);
    });
  }

  async function saveLabels() {
    const { labels, errors } = draftToLabels(labelDraft, savedEntities);
    if (errors.length) {
      setError(errors.join(" "));
      return;
    }
    await guard(async () => {
      await api.saveDocumentLabels(selectedDataset!, labelling!, labels);
      await refreshDocuments(selectedDataset!);
      await refreshDatasets();
      setLabelling(null);
    });
  }

  function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !selectedDataset) return;
    void guard(async () => {
      await api.addDatasetDocument(selectedDataset, file);
      await refreshDocuments(selectedDataset);
      await refreshDatasets();
    });
    event.target.value = "";
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
              <button key={dataset.name} className={`dataset-option ${selectedDataset === dataset.name ? "selected" : ""}`} onClick={() => { setSelectedDataset(dataset.name); setLabelling(null); }}>
                <span className="radio">{selectedDataset === dataset.name && <span />}</span>
                <span className="model-option-copy"><strong>{dataset.name}</strong><small>{dataset.document_count} documents · {dataset.labelled_count} labelled</small></span>
                <span className="model-specs">{dataset.labelled_count === 0 && <em className="warn">No ground truth</em>}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedDataset && (
        <div className="settings-card">
          <div className="settings-card-heading">
            <span className="settings-card-icon"><Tag size={18} /></span>
            <div><h3>{selectedDataset}</h3><p>A document is only scored on the entities you labelled.</p></div>
            <button className="add-entity-button" onClick={() => uploadInput.current?.click()}><UploadCloud size={14} /> Add PDF</button>
          </div>
          <input ref={uploadInput} type="file" accept="application/pdf,.pdf" onChange={handleUpload} hidden />

          {validatedRuns.length > 0 && (
            <div className="promote-row">
              <History size={15} />
              <span>Reuse a document you already reviewed:</span>
              <select defaultValue="" onChange={(event) => { const runId = Number(event.target.value); event.target.value = ""; if (runId) void guard(async () => { await api.promoteRun(selectedDataset, runId); await refreshDocuments(selectedDataset); await refreshDatasets(); }); }}>
                <option value="">Choose a validated run…</option>
                {validatedRuns.map((run) => <option key={run.id} value={run.id}>{run.filename} · {run.created_at.slice(0, 10)}</option>)}
              </select>
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
                  <button className="secondary-button small" onClick={() => openLabels(document.name)}>{document.labelled ? "Edit labels" : "Add labels"}</button>
                  <button className="icon-button" aria-label={`Remove ${document.name}`} onClick={() => guard(async () => { await api.removeDatasetDocument(selectedDataset, document.name); await refreshDocuments(selectedDataset); await refreshDatasets(); })}><Trash2 size={15} /></button>
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
              {savedEntities.map((entity) => {
                const entry = labelDraft[entity.name] ?? { mode: "skip" as LabelMode, text: "" };
                return (
                  <div className="label-row" key={entity.name}>
                    <div className="label-name"><span>{entity.name}</span><small>{formatLabels[entity.format]}</small></div>
                    <select value={entry.mode} onChange={(event) => setLabelDraft({ ...labelDraft, [entity.name]: { ...entry, mode: event.target.value as LabelMode } })}>
                      {Object.entries(labelModes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                    <input disabled={entry.mode !== "value"} placeholder={entry.mode === "value" ? "Correct value" : "—"} value={entry.text} onChange={(event) => setLabelDraft({ ...labelDraft, [entity.name]: { mode: "value", text: event.target.value } })} />
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
            <button className="primary-button" disabled={!selectedDataset || busy || !isModelReady} onClick={() => guard(async () => { await api.startEvaluation(selectedDataset!); await refreshEvaluations(); })}>
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
          <div><h3>Past runs</h3><p>Each run remembers the prompts it used, so two runs are comparable.</p></div>
        </div>
        {evaluations.length === 0 ? (
          <div className="models-empty"><AlertCircle size={18} /><span>No test has been run yet.</span></div>
        ) : (
          <div className="evaluation-list">
            {evaluations.map((evaluation) => (
              <button key={evaluation.id} className={`evaluation-row ${openEvaluation?.id === evaluation.id ? "selected" : ""}`} onClick={() => guard(async () => setOpenEvaluation(await api.evaluation(evaluation.id)))}>
                <span className={`status-tag ${evaluation.status}`}>{evaluation.status}</span>
                <span className="evaluation-meta"><strong>{evaluation.dataset}</strong><small>{evaluation.created_at.replace("T", " ").slice(0, 16)} · {evaluation.model}</small></span>
                <span className={`evaluation-score ${accuracyClass(evaluation.metrics.accuracy)}`}>{percent(evaluation.metrics.accuracy)}</span>
                <small>{evaluation.metrics.matched}/{evaluation.metrics.total} fields</small>
              </button>
            ))}
          </div>
        )}
      </div>

      {openEvaluation && (
        <div className="settings-card">
          <div className="settings-card-heading">
            <span className="settings-card-icon"><CheckCircle2 size={18} /></span>
            <div><h3>Run #{openEvaluation.id} · {openEvaluation.dataset}</h3><p>{openEvaluation.model} · {openEvaluation.completed_documents} of {openEvaluation.total_documents} documents</p></div>
            <button className="icon-button" aria-label="Close" onClick={() => setOpenEvaluation(null)}><X size={15} /></button>
          </div>

          {openEvaluation.error && <div className="alert error-alert"><AlertCircle size={17} /><span>{openEvaluation.error}</span></div>}

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
                    : <small>{document.items.filter((item) => item.matched).length}/{document.items.length} correct{document.elapsed_ms ? ` · ${(document.elapsed_ms / 1000).toFixed(1)} s` : ""}</small>}
                </div>
                {document.error && <p className="field-warning"><AlertCircle size={11} /> {document.error}</p>}
                {document.items.filter((item) => !item.matched).map((item) => (
                  <div className="mismatch-row" key={item.entity}>
                    <span className="mismatch-entity">{item.entity}</span>
                    <span className="mismatch-expected">expected <code>{describeValue(item.expected)}</code></span>
                    <span className="mismatch-actual">got <code>{describeValue(item.actual)}</code></span>
                    <span className={`confidence-pill ${item.confidence}`}><i /> {item.confidence}</span>
                  </div>
                ))}
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
