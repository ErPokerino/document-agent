"use client";

import {
  AlertCircle,
  Braces,
  Check,
  ChevronRight,
  Cloud,
  Cpu,
  Database,
  Download,
  ExternalLink,
  Eye,
  FlaskConical,
  FileJson,
  FileText,
  LayoutDashboard,
  LoaderCircle,
  Pencil,
  RotateCcw,
  Scissors,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  Workflow,
  X,
} from "lucide-react";
import { ChangeEvent, DragEvent, Fragment, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { resolveBootstrap } from "../lib/bootstrap";
import { Datasets } from "./datasets";
import { Lab } from "./lab";
import { Models, formatBytes, modelStateLabels } from "./models";
import { Pipelines } from "./pipeline";
import { Settings } from "./settings";
import { stepLabels } from "../lib/pipeline-editor";
import { Prompts } from "./prompts";
import { buildReviewedExport } from "../lib/review";
import { validateSettingsDraft } from "../lib/validation";
import type {
  AppSettings,
  Confidence,
  EntityDefinition,
  EntityFormat,
  ExtractionResponse,
  HealthStatus,
  ModelInfo,
  ModelLoadResponse,
  GeminiKeyStatus,
} from "../lib/types";

type View = "workspace" | "prompts" | "pipelines" | "datasets" | "lab" | "models" | "settings";
const sectionCopy: Record<View, { eyebrow: string; title: string }> = {
  workspace: { eyebrow: "Invoice extraction", title: "Document workspace" },
  prompts: { eyebrow: "Extraction target", title: "Prompts" },
  pipelines: { eyebrow: "How a document is processed", title: "Pipelines" },
  datasets: { eyebrow: "Ground truth", title: "Datasets" },
  lab: { eyebrow: "Extraction quality", title: "Lab" },
  models: { eyebrow: "Configuration", title: "Models" },
  settings: { eyebrow: "Preferences", title: "Settings" },
};

type ProcessState = "idle" | "ready" | "processing" | "complete" | "error";

const formatLabels: Record<EntityFormat, string> = {
  text: "Text",
  date: "Date · YYYY-MM-DD",
  currency: "Currency · ISO 4217",
  decimal: "Decimal number",
  integer: "Integer number",
};

const confidenceLabels: Record<Confidence, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

function formatModelName(modelId: string, models: ModelInfo[]) {
  return models.find((model) => model.id === modelId)?.name ?? modelId;
}

function prettyName(name: string) {
  return name.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

export default function Home() {
  const [view, setView] = useState<View>("workspace");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [processState, setProcessState] = useState<ProcessState>("idle");
  const [result, setResult] = useState<ExtractionResponse | null>(null);
  const [editableValues, setEditableValues] = useState<Record<string, string>>({});
  const [editedFields, setEditedFields] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  // Null until the backend answers. There is deliberately no local default:
  // saving one would overwrite the stored prompts with frontend constants.
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draftSettings, setDraftSettings] = useState<AppSettings | null>(null);
  const [pipelineShape, setPipelineShape] = useState<string[]>([]);
  const [settingsState, setSettingsState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [modelsRefreshing, setModelsRefreshing] = useState(false);
  const [modelLoadState, setModelLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [modelLoadReport, setModelLoadReport] = useState<ModelLoadResponse | null>(null);
  const [reviewState, setReviewState] = useState<"idle" | "saving" | "saved">("idle");
  const [geminiKey, setGeminiKey] = useState("");
  const [keyStatus, setKeyStatus] = useState<GeminiKeyStatus | null>(null);
  const [verifying, setVerifying] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const previewUrlRef = useRef<string | null>(null);

  useEffect(() => {
    async function bootstrap() {
      const resolved = resolveBootstrap(
        await Promise.allSettled([api.health(), api.settings(), api.models()]),
      );
      setHealth(resolved.health);
      setModels(resolved.models);
      if (resolved.settings) {
        setSettings(resolved.settings);
        setDraftSettings(resolved.settings);
      }
      if (resolved.error) {
        setSettingsError(resolved.error);
        setSettingsState("error");
      }
      await api.geminiKeyStatus().then(setKeyStatus).catch(() => undefined);
    }
    bootstrap();
  }, []);

  // "system" means no attribute at all, so the media query in the stylesheet
  // decides and keeps deciding while the app is open.
  useEffect(() => {
    const theme = draftSettings?.theme ?? "system";
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [draftSettings?.theme]);

  // The strip below the result describes the pipeline in use, so it has to be
  // read back whenever that choice changes.
  useEffect(() => {
    const chosen = settings?.pipeline;
    if (!chosen) return;
    let active = true;
    void Promise.all([api.pipelines(), api.pipelineSteps()])
      .then(([saved, catalogue]) => {
        if (!active) return;
        const pipeline = saved.find((candidate) => candidate.name === chosen);
        setPipelineShape(pipeline ? stepLabels(pipeline.steps, catalogue) : []);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [settings?.pipeline]);

  useEffect(() => {
    let active = true;

    async function refreshModels() {
      setModelsRefreshing(true);
      try {
        const discovered = await api.models();
        if (active) setModels(discovered);
      } catch {
        // Keep the last successful discovery result while LM Studio is unavailable.
      } finally {
        if (active) setModelsRefreshing(false);
      }
    }

    void refreshModels();
    const timer = window.setInterval(refreshModels, 10_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  function selectFile(selected: File | null) {
    setError(null);
    setResult(null);
    setEditableValues({});
    setEditedFields(new Set());
    if (!selected) return;
    if (!selected.name.toLowerCase().endsWith(".pdf")) {
      setError("Select a PDF document.");
      setProcessState("error");
      return;
    }
    if (selected.size > 20 * 1024 * 1024) {
      setError("The document exceeds the 20 MB limit.");
      setProcessState("error");
      return;
    }
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = URL.createObjectURL(selected);
    setPreviewUrl(previewUrlRef.current);
    setFile(selected);
    setProcessState("ready");
  }

  function handleFileInput(event: ChangeEvent<HTMLInputElement>) {
    selectFile(event.target.files?.[0] ?? null);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files?.[0] ?? null);
  }

  function resetDocument() {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setPreviewUrl(null);
    setFile(null);
    setResult(null);
    setEditableValues({});
    setEditedFields(new Set());
    setError(null);
    setProcessState("idle");
    if (fileInput.current) fileInput.current.value = "";
  }

  async function processDocument() {
    if (!file) return;
    if (!isModelReady) {
      setError("The active model is not ready. Open Settings and use Load & warm up first.");
      return;
    }
    setProcessState("processing");
    setError(null);
    setResult(null);
    setEditableValues({});
    setEditedFields(new Set());
    try {
      const extraction = await api.extract(file);
      setResult(extraction);
      setEditableValues(
        Object.fromEntries(
          Object.entries(extraction.data).map(([name, field]) => [
            name,
            field.value === null ? "" : String(field.value),
          ]),
        ),
      );
      setProcessState("complete");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Processing failed");
      setProcessState("error");
    }
  }

  function validateDraft() {
    if (!draftSettings) return "Settings have not been loaded from the backend yet.";
    return validateSettingsDraft(draftSettings.prompts);
  }

  async function usePipeline(name: string) {
    if (!draftSettings) return;
    const saved = await api.saveSettings({
      ...draftSettings,
      pipeline: name,
      gemini: { ...draftSettings.gemini, api_key: geminiKey },
    });
    setSettings(saved);
    setDraftSettings(saved);
    setGeminiKey("");
  }

  async function saveSettings() {
    if (!draftSettings) return;
    const validationError = validateDraft();
    if (validationError) {
      setSettingsError(validationError);
      setSettingsState("error");
      return;
    }
    setSettingsState("saving");
    setSettingsError(null);
    try {
      // An empty key field means "keep the stored one"; the backend never
      // sends the real key back, so the draft always carries a blank.
      const settingsToSave = {
        ...draftSettings,
        gemini: { ...draftSettings.gemini, api_key: geminiKey },
      };
      const saved = await api.saveSettings(settingsToSave);
      setSettings(saved);
      setDraftSettings(saved);
      setGeminiKey("");
      await api.geminiKeyStatus().then(setKeyStatus).catch(() => undefined);
      setHealth((current) => current && { ...current, active_model: saved.model });
      setResult(null);
      setEditableValues({});
      setEditedFields(new Set());
      if (file) setProcessState("ready");
      setSettingsState("saved");
      window.setTimeout(() => setSettingsState("idle"), 1800);
    } catch (requestError) {
      setSettingsError(requestError instanceof Error ? requestError.message : "Save failed");
      setSettingsState("error");
    }
  }

  async function loadSelectedModel() {
    if (!draftSettings) return;
    const validationError = validateDraft();
    if (validationError) {
      setSettingsError(validationError);
      setModelLoadState("error");
      return;
    }
    setModelLoadState("loading");
    setModelLoadReport(null);
    setSettingsError(null);
    try {
      const settingsToSave = {
        ...draftSettings,
        gemini: { ...draftSettings.gemini, api_key: geminiKey },
      };
      const saved = await api.saveSettings(settingsToSave);
      setSettings(saved);
      setDraftSettings(saved);
      setGeminiKey("");
      setHealth((current) => current && { ...current, active_model: saved.model });

      const report = await api.loadModel(saved.model);
      setModelLoadReport(report);
      setModels(await api.models());
      setModelLoadState("ready");
      setResult(null);
      if (file) setProcessState("ready");
    } catch (requestError) {
      setSettingsError(requestError instanceof Error ? requestError.message : "Model loading failed");
      setModelLoadState("error");
      setModels(await api.models().catch(() => models));
    }
  }

  function downloadJson() {
    if (!result || !settings) return;
    const reviewedData = buildReviewedExport(
      settings.prompts.entities,
      result.data,
      editableValues,
      editedFields,
    );
    const blob = new Blob([JSON.stringify(reviewedData, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `${result.filename.replace(/\.pdf$/i, "")}.json`;
    anchor.click();
    URL.revokeObjectURL(href);
  }

  async function markReviewed() {
    if (!result?.run_id || !settings) return;
    setReviewState("saving");
    setError(null);
    try {
      // Every field is sent, not only the edited ones: a run where the model
      // was right about everything is the most useful ground truth there is.
      const reviewed = buildReviewedExport(
        settings.prompts.entities,
        result.data,
        editableValues,
        editedFields,
      );
      await api.saveCorrections(
        result.run_id,
        Object.fromEntries(Object.entries(reviewed).map(([name, field]) => [name, field.value])),
      );
      setReviewState("saved");
      window.setTimeout(() => setReviewState("idle"), 2000);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The corrections could not be saved");
      setReviewState("idle");
    }
  }

  function updateReviewValue(entity: EntityDefinition, value: string) {
    const normalized = entity.format === "currency" ? value.toUpperCase() : value;
    setEditableValues((current) => ({ ...current, [entity.name]: normalized }));
    setEditedFields((current) => new Set(current).add(entity.name));
  }

  function revertReviewValue(entityName: string) {
    if (!result) return;
    const originalValue = result.data[entityName]?.value;
    setEditableValues((current) => ({
      ...current,
      [entityName]: originalValue === null || originalValue === undefined ? "" : String(originalValue),
    }));
    setEditedFields((current) => {
      const next = new Set(current);
      next.delete(entityName);
      return next;
    });
  }

  const settingsLoaded = settings !== null && draftSettings !== null;
  // Where documents actually go. Saying "local" while pages are being uploaded
  // to Google would be the worst kind of wrong copy.
  const usingHostedModel = settings?.provider === "gemini";
  const privacyHeading = usingHostedModel ? "Sent to Google" : "Private processing";
  const privacyDetail = usingHostedModel
    ? "Page images are uploaded to the Gemini API for extraction."
    : "Files and data are processed exclusively by the local model.";
  const configuredEntities = settings?.prompts.entities ?? [];
  const activeModelName = settings ? formatModelName(settings.model, models) : "No model selected";
  const isConnected = health?.lm_studio === true;
  const activeModel = models.find((model) => model.id === settings?.model);
  const isModelReady = activeModel?.ready === true;
  const activeModelStatus = activeModel ? modelStateLabels[activeModel.runtime_state] : "Model unavailable";
  const unresolvedWarningCount = result
    ? Object.entries(result.data).filter(([name, field]) => field.warning && !editedFields.has(name)).length
    : 0;

  const extractionPanel = (
    <section className={`schema-panel review-schema ${processState === "processing" ? "processing" : ""}`}>
      <div className="panel-heading">
        <div><h2>Extracted data</h2></div>
        <span className={`result-badge ${unresolvedWarningCount ? "warning" : processState}`}>
          {processState === "processing" && <LoaderCircle className="spin" size={10} />}
          {processState === "complete" && unresolvedWarningCount === 0 && <Check size={10} />}
          {unresolvedWarningCount > 0 && <AlertCircle size={10} />}
          {unresolvedWarningCount > 0 ? "Review needed" : processState === "complete" ? "Complete" : processState === "processing" ? "Processing" : "Waiting"}
        </span>
      </div>

      <p className="panel-copy">
        {result
          ? `Processed pages ${result.processing.first_processed_page}–${result.processing.last_processed_page} of ${result.processing.page_count} in ${(result.elapsed_ms / 1000).toFixed(1)} s (model load excluded) · Review and edit values before export.`
          : "The schema will be populated automatically after processing."}
      </p>
      {result?.processing.time_to_first_token_seconds !== null && result?.processing.time_to_first_token_seconds !== undefined && (
        <p className="field-help">
          Prompt and image to first token: {result.processing.time_to_first_token_seconds.toFixed(2)} s
          {result.processing.prediction_time_seconds !== null && result.processing.prediction_time_seconds !== undefined && ` · LM Studio prediction: ${result.processing.prediction_time_seconds.toFixed(2)} s`}
          {result.processing.tokens_per_second !== null && result.processing.tokens_per_second !== undefined && ` · ${result.processing.tokens_per_second.toFixed(2)} tok/s`}. Identical repeated runs can be much faster because LM Studio may reuse its prompt and image cache.
        </p>
      )}

      <div className="field-list">
        {configuredEntities.map((entity) => {
          const field = result?.data[entity.name];
          const edited = editedFields.has(entity.name);
          const editableValue = editableValues[entity.name] ?? "";
          const inputType = entity.format === "date"
            ? "date"
            : entity.format === "decimal" || entity.format === "integer"
              ? "number"
              : "text";
          return (
            <div className={`field-row ${field?.warning && !edited ? "has-warning" : ""}`} key={entity.name}>
              <div className="field-meta"><span>{prettyName(entity.name)}</span><code>{entity.name}</code></div>
              <div className={`field-value ${editableValue ? "populated" : ""}`}>
                {field ? (
                  <div className="editable-value">
                    <input
                      aria-label={`Edit ${prettyName(entity.name)}`}
                      type={inputType}
                      step={entity.format === "integer" ? "1" : entity.format === "decimal" ? "any" : undefined}
                      maxLength={entity.format === "currency" ? 3 : undefined}
                      placeholder="Enter value"
                      value={editableValue}
                      onChange={(event) => updateReviewValue(entity, event.target.value)}
                    />
                    <div className="value-controls">
                      <span className={`confidence-pill ${field.confidence}`} title="Original model confidence"><i /> {confidenceLabels[field.confidence]}</span>
                      {edited && <span className="manual-pill"><Pencil size={9} /> Edited</span>}
                      {edited && <button className="revert-value" onClick={() => revertReviewValue(entity.name)} aria-label={`Revert ${prettyName(entity.name)}`} title="Restore model value"><RotateCcw size={11} /></button>}
                    </div>
                    {field.warning && !edited && <span className="field-warning"><AlertCircle size={11} /> {field.warning}</span>}
                  </div>
                ) : (
                  <span className="empty-value">—</span>
                )}
                <small>{formatLabels[entity.format]}</small>
              </div>
            </div>
          );
        })}
      </div>

      <div className="confidence-legend">
        <span>Model-estimated confidence</span>
        <div><i className="high" /> High <i className="medium" /> Medium <i className="low" /> Low</div>
      </div>

      <div className="schema-footer">
        <span><FileJson size={13} /> Dynamic JSON Schema</span>
        <button className="export-button" disabled={!result?.run_id || reviewState === "saving"} onClick={markReviewed} title="Store these values as verified, so this document can become ground truth in Prompt Lab">
          {reviewState === "saved" ? <><Check size={14} /> Saved as verified</> : <><ShieldCheck size={14} /> Mark as reviewed</>}
        </button>
        <button className="export-button" disabled={!result} onClick={downloadJson}><Download size={14} /> Export JSON</button>
      </div>
    </section>
  );

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><FileText size={18} strokeWidth={2.2} /></span>
          <div><strong>DocuFlow</strong><span>Document intelligence</span></div>
        </div>

        <nav className="nav-list" aria-label="Main navigation">
          <button className={`nav-item ${view === "workspace" ? "active" : ""}`} onClick={() => setView("workspace")}>
            <LayoutDashboard size={17} /> Workspace
          </button>
          <button className={`nav-item ${view === "prompts" ? "active" : ""}`} onClick={() => setView("prompts")}>
            <Braces size={17} /> Prompts
          </button>
          <button className={`nav-item ${view === "pipelines" ? "active" : ""}`} onClick={() => setView("pipelines")}>
            <Workflow size={17} /> Pipelines
          </button>
          <button className={`nav-item ${view === "datasets" ? "active" : ""}`} onClick={() => setView("datasets")}>
            <Database size={17} /> Datasets
          </button>
          <button className={`nav-item ${view === "lab" ? "active" : ""}`} onClick={() => setView("lab")}>
            <FlaskConical size={17} /> Lab
          </button>
          <button className={`nav-item ${view === "models" ? "active" : ""}`} onClick={() => setView("models")}>
            <Cpu size={17} /> Models
          </button>
          <button className={`nav-item ${view === "settings" ? "active" : ""}`} onClick={() => setView("settings")}>
            <SlidersHorizontal size={17} /> Settings
          </button>
        </nav>

        <div className="sidebar-bottom">
          <div className={`local-status ${usingHostedModel ? (keyStatus?.configured ? "online" : "offline") : isConnected ? "online" : "offline"}`}>
            <span className="status-dot" />
            <div>
              <strong>{usingHostedModel ? "Google Gemini" : "LM Studio"}</strong>
              <small>{usingHostedModel ? "Hosted API" : "Local inference"}</small>
            </div>
            <span className="status-pill">
              {usingHostedModel
                ? keyStatus?.configured ? "Key set" : "No key"
                : isConnected ? "Online" : "Offline"}
            </span>
          </div>

        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{sectionCopy[view].eyebrow}</p>
            <h1>{sectionCopy[view].title}</h1>
          </div>
          <div className="topbar-chips">
            <button className="model-chip" onClick={() => setView("pipelines")} title="Change it in Pipelines">
              <span className="model-icon"><Workflow size={15} /></span>
              <div><small>Pipeline</small><strong>{settings?.pipeline ?? "—"}</strong></div>
            </button>
            <button className="model-chip" onClick={() => setView("models")} title="Change it in Models">
              <span className="model-icon"><Cpu size={15} /></span>
              <div><small>{activeModelStatus}</small><strong>{activeModelName}</strong></div>
              <span className={`connection-light ${isConnected && isModelReady ? "online" : ""}`} />
            </button>
          </div>
        </header>

        {view === "workspace" ? (
          <>
            {error && (
              <div className="alert error-alert" role="alert"><AlertCircle size={17} /><span>{error}</span><button onClick={() => setError(null)} aria-label="Close"><X size={15} /></button></div>
            )}

            {result?.processing.cut_applied && (
              <div className="alert chunk-alert" role="status">
                <Scissors size={17} />
                <span><strong>Document cut applied.</strong> Pages {result.processing.first_processed_page}–{result.processing.last_processed_page} of {result.processing.page_count} were sent in one call, based on the configured maximum of {result.processing.configured_page_limit} pages.</span>
              </div>
            )}

            {!file ? (
              <div className="content-grid">
                <section className="upload-panel">
                  <div className="panel-heading">
                    <div><h2>Upload invoice</h2></div>
                    <span className="format-badge">PDF</span>
                  </div>

                  <div
                    className={`drop-zone ${dragging ? "dragging" : ""}`}
                    onDragEnter={() => setDragging(true)}
                    onDragLeave={() => setDragging(false)}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={handleDrop}
                  >
                    <div className="upload-icon"><UploadCloud size={23} /></div>
                    <h3>Drop the document here</h3>
                    <p>or select an invoice from your computer</p>
                    <button className="primary-button" onClick={() => fileInput.current?.click()}>Select PDF</button>
                    <small>Maximum 20 MB · Large files follow the configured page limit</small>
                  </div>
                  <input ref={fileInput} type="file" accept="application/pdf,.pdf" onChange={handleFileInput} hidden />
                  <div className={`privacy-note ${usingHostedModel ? "hosted" : ""}`}>{usingHostedModel ? <Cloud size={16} /> : <ShieldCheck size={16} />}<p><strong>{privacyHeading}</strong> {privacyDetail}</p></div>
                </section>
                {extractionPanel}
              </div>
            ) : (
              <div className="review-session">
                <section className="document-session-bar">
                  <div className="session-file">
                    <div className="document-preview"><FileText size={22} /><span>PDF</span></div>
                    <div className="document-details"><small>Selected document</small><h3>{file.name}</h3><p>{formatBytes(file.size)}</p></div>
                  </div>
                  <div className={`session-privacy ${usingHostedModel ? "hosted" : ""}`}>{usingHostedModel ? <Cloud size={15} /> : <ShieldCheck size={15} />}<span>{usingHostedModel ? "Sent to Google" : "Processed locally"}</span></div>
                  <div className="session-actions">
                    {processState === "complete" ? (
                      <button className="secondary-button session-process" disabled={!isModelReady} onClick={processDocument}><RotateCcw size={15} /> Process again</button>
                    ) : (
                      <button className="primary-button session-process" disabled={processState === "processing" || !isConnected || !isModelReady} onClick={processDocument}>
                        {processState === "processing" ? <><LoaderCircle className="spin" size={16} /> Processing…</> : <><Sparkles size={16} /> Analyze invoice</>}
                      </button>
                    )}
                    <button className="icon-button" onClick={resetDocument} aria-label="Remove document"><Trash2 size={16} /></button>
                  </div>
                  {!isConnected && <small className="session-warning">Start LM Studio to process this document</small>}
                  {isConnected && !isModelReady && <button className="session-warning action" onClick={() => setView("models")}>Prepare the active model in Models before processing</button>}
                </section>
                <div className="review-grid">
                  {previewUrl && (
                    <section className="pdf-preview-panel">
                      <div className="preview-toolbar">
                        <div><Eye size={15} /><span>Document preview</span></div>
                        <div className="preview-actions">
                          {result && <span className="processed-badge">Model pages {result.processing.first_processed_page}–{result.processing.last_processed_page}</span>}
                          <a href={previewUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open</a>
                        </div>
                      </div>
                      <iframe src={previewUrl} title={`Preview of ${file.name}`} />
                    </section>
                  )}
                  {extractionPanel}
                </div>
              </div>
            )}

            <footer className="pipeline-strip">
              <span>{settings?.pipeline ?? "Current pipeline"}</span>
              <div className={`pipeline-step ${isModelReady ? "done" : "active"}`}><b>{isModelReady ? <Check size={10} /> : "1"}</b> Model ready</div>
              <ChevronRight size={13} />
              <div className={`pipeline-step ${file ? "done" : ""}`}><b>{file ? <Check size={10} /> : "2"}</b> PDF input</div>
              {pipelineShape.map((label, index) => (
                <Fragment key={`${label}-${index}`}>
                  <ChevronRight size={13} />
                  <div className={`pipeline-step ${processState === "processing" ? "active pulse" : result ? "done" : ""}`}>
                    <b>{result ? <Check size={10} /> : index + 3}</b> {label}
                  </div>
                </Fragment>
              ))}
              <ChevronRight size={13} />
              <div className={`pipeline-step ${result ? "done" : ""}`}><b>{result ? <Check size={10} /> : pipelineShape.length + 3}</b> JSON validation</div>
            </footer>
          </>
        ) : !draftSettings ? (
          <section className="settings-layout wide">
            <div className="settings-intro">
              <SlidersHorizontal size={19} />
              <div>
                <h2>Agent configuration</h2>
                <p>{settingsError ?? "Loading the configuration stored by the backend…"}</p>
              </div>
            </div>
            {settingsError && (
              <div className="alert error-alert" role="alert">
                <AlertCircle size={17} />
                <span>Start the backend and reload the page. Settings are not editable until they have been read, so nothing can overwrite the prompts stored on disk.</span>
              </div>
            )}
          </section>
        ) : view === "prompts" ? (
          <Prompts
            draftSettings={draftSettings}
            setDraftSettings={setDraftSettings}
            onSave={saveSettings}
            settingsState={settingsState}
            settingsError={settingsError}
          />
        ) : view === "pipelines" ? (
          <Pipelines
            draftSettings={draftSettings}
            entities={configuredEntities}
            onUse={usePipeline}
          />
        ) : view === "settings" ? (
          <Settings
            draftSettings={draftSettings}
            setDraftSettings={setDraftSettings}
            onSave={saveSettings}
            settingsState={settingsState}
            settingsError={settingsError}
          />
        ) : view === "datasets" ? (
          <Datasets savedEntities={configuredEntities} isModelReady={isModelReady} />
        ) : view === "lab" ? (
          <Lab draftSettings={draftSettings} isModelReady={isModelReady} />
        ) : (
          <Models
            models={models}
            draftSettings={draftSettings}
            setDraftSettings={setDraftSettings}
            geminiKey={geminiKey}
            setGeminiKey={setGeminiKey}
            keyStatus={keyStatus}
            setKeyStatus={setKeyStatus}
            verifying={verifying}
            setVerifying={setVerifying}
            settingsError={settingsError}
            setSettingsError={setSettingsError}
            settingsState={settingsState}
            settingsLoaded={settingsLoaded}
            onSave={saveSettings}
            loadSelectedModel={loadSelectedModel}
            modelLoadState={modelLoadState}
            modelLoadReport={modelLoadReport}
            setModelLoadState={setModelLoadState}
            setModelLoadReport={setModelLoadReport}
            modelsRefreshing={modelsRefreshing}
            isConnected={isConnected}
            processState={processState}
          />
        )}
      </section>
    </main>
  );
}
