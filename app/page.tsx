"use client";

import {
  AlertCircle,
  Braces,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Cloud,
  Cpu,
  Download,
  ExternalLink,
  Eye,
  FlaskConical,
  KeyRound,
  FileJson,
  FileText,
  LayoutDashboard,
  LoaderCircle,
  Pencil,
  Power,
  RefreshCw,
  RotateCcw,
  Save,
  Scissors,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { resolveBootstrap } from "../lib/bootstrap";
import { PromptLab } from "./prompt-lab";
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
  ModelRuntimeState,
} from "../lib/types";

type View = "workspace" | "lab" | "settings";
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

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatModelName(modelId: string, models: ModelInfo[]) {
  return models.find((model) => model.id === modelId)?.name ?? modelId;
}

function prettyName(name: string) {
  return name.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

function formatDuration(ms: number) {
  return `${(ms / 1000).toFixed(1)} s`;
}

const modelStateLabels: Record<ModelRuntimeState, string> = {
  not_loaded: "Model not loaded",
  loaded: "Model in memory",
  loading: "Loading model",
  warming_up: "Warming up model",
  ready: "Model ready",
  error: "Model preparation failed",
  profile_mismatch: "Loaded with the wrong profile",
};

const modelBadgeLabels: Record<ModelRuntimeState, string> = {
  not_loaded: "Available",
  loaded: "In memory",
  loading: "Loading",
  warming_up: "Warming up",
  ready: "Ready",
  error: "Preparation failed",
  profile_mismatch: "Needs reload",
};

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
  const [settingsState, setSettingsState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [modelsRefreshing, setModelsRefreshing] = useState(false);
  const [modelLoadState, setModelLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [modelLoadReport, setModelLoadReport] = useState<ModelLoadResponse | null>(null);
  const [pageLimitInput, setPageLimitInput] = useState("");
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
        setPageLimitInput(String(resolved.settings.max_pages_to_analyze));
      }
      if (resolved.error) {
        setSettingsError(resolved.error);
        setSettingsState("error");
      }
      await api.geminiKeyStatus().then(setKeyStatus).catch(() => undefined);
    }
    bootstrap();
  }, []);

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
    return validateSettingsDraft(draftSettings.prompts, pageLimitInput);
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
        max_pages_to_analyze: Number(pageLimitInput),
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
        max_pages_to_analyze: Number(pageLimitInput),
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
  const selectedDraftModel = models.find((model) => model.id === draftSettings?.model);
  const activeModel = models.find((model) => model.id === settings?.model);
  const selectedRuntimeState = selectedDraftModel?.runtime_state ?? "not_loaded";
  const selectedModelPreparing = selectedRuntimeState === "loading" || selectedRuntimeState === "warming_up" || modelLoadState === "loading";
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
          <button className={`nav-item ${view === "lab" ? "active" : ""}`} onClick={() => setView("lab")}>
            <FlaskConical size={17} /> Prompt Lab
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
          <button className={`nav-item ${view === "settings" ? "active" : ""}`} onClick={() => setView("settings")}>
            <Settings size={17} /> Settings
          </button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{view === "workspace" ? "Invoice extraction" : view === "lab" ? "Extraction quality" : "Configuration"}</p>
            <h1>{view === "workspace" ? "Document workspace" : view === "lab" ? "Prompt Lab" : "Settings"}</h1>
          </div>
          <div className="model-chip" title="Change the model in Settings">
            <span className="model-icon"><Cpu size={15} /></span>
            <div><small>{activeModelStatus}</small><strong>{activeModelName}</strong></div>
            <span className={`connection-light ${isConnected && isModelReady ? "online" : ""}`} />
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
                  {isConnected && !isModelReady && <button className="session-warning action" onClick={() => setView("settings")}>Prepare the active model in Settings before processing</button>}
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
              <span>Current pipeline</span>
              <div className={`pipeline-step ${isModelReady ? "done" : "active"}`}><b>{isModelReady ? <Check size={10} /> : "1"}</b> Model ready</div>
              <ChevronRight size={13} />
              <div className={`pipeline-step ${file ? "done" : ""}`}><b>{file ? <Check size={10} /> : "2"}</b> PDF input</div>
              <ChevronRight size={13} />
              <div className={`pipeline-step ${processState === "processing" ? "active" : result ? "done" : ""}`}><b>{result ? <Check size={10} /> : "3"}</b> Render first pages</div>
              <ChevronRight size={13} />
              <div className={`pipeline-step ${processState === "processing" ? "active pulse" : result ? "done" : ""}`}><b>{result ? <Check size={10} /> : "4"}</b> Single vision call</div>
              <ChevronRight size={13} />
              <div className={`pipeline-step ${result ? "done" : ""}`}><b>{result ? <Check size={10} /> : "5"}</b> JSON validation</div>
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
        ) : view === "lab" ? (
          <PromptLab
            draftSettings={draftSettings}
            setDraftSettings={setDraftSettings}
            savedEntities={configuredEntities}
            onSave={saveSettings}
            settingsState={settingsState}
            settingsError={settingsError}
            isModelReady={isModelReady}
          />
        ) : (
          <section className="settings-layout wide">
            <div className="settings-intro">
              <SlidersHorizontal size={19} />
              <div><h2>Agent configuration</h2><p>Model, prompts and entities are stored locally and applied to every subsequent run.</p></div>
            </div>

            {settingsError && <div className="alert error-alert"><AlertCircle size={17} />{settingsError}</div>}

                <div className="settings-card">
                  <div className="settings-card-heading">
                    <span className="settings-card-icon"><Server size={18} /></span>
                    <div><h3>LM Studio connection</h3><p>OpenAI-compatible endpoint used by the backend.</p></div>
                    <span className={`connection-badge ${isConnected ? "online" : ""}`}><CircleDot size={12} /> {isConnected ? "Connected" : "Disconnected"}</span>
                  </div>
                  <label className="input-label" htmlFor="endpoint">Local endpoint</label>
                  <input id="endpoint" className="text-input" value={draftSettings.lm_studio_url} onChange={(event) => setDraftSettings({ ...draftSettings, lm_studio_url: event.target.value })} />
                </div>

                <div className="settings-card">
                  <div className="settings-card-heading">
                    <span className="settings-card-icon"><Cpu size={18} /></span>
                    <div><h3>Vision model</h3><p>Local models come from LM Studio, refreshed every 10 seconds. Hosted models run on Google&apos;s servers and need only an API key.</p></div>
                    <span className="connection-badge"><RefreshCw className={modelsRefreshing ? "spin" : ""} size={12} /> Auto refresh</span>
                  </div>
                  <div className="model-list">
                    {models.length === 0 ? (
                      <div className="models-empty"><AlertCircle size={18} /><span>No vision model detected. Make sure LM Studio is running.</span></div>
                    ) : models.map((model) => {
                      const selected = draftSettings?.model === model.id;
                      return (
                        <button key={model.id} className={`model-option ${selected ? "selected" : ""}`} onClick={() => { setDraftSettings({ ...draftSettings, model: model.id, provider: model.provider }); setModelLoadState("idle"); setModelLoadReport(null); }}>
                          <span className="radio">{selected && <span />}</span><span className="model-option-icon">{model.provider === "gemini" ? <Sparkles size={17} /> : <Eye size={17} />}</span>
                          <span className="model-option-copy"><strong>{model.name}</strong><small>{model.id}</small></span>
                          <span className={`provider-tag ${model.provider}`}>{model.provider === "gemini" ? "Google API" : "Local"}</span>
                          <span className="model-specs">{model.parameters && <em>{model.parameters}</em>}{model.quantization && <em>{model.quantization}</em>}{model.size_bytes && <em>{formatBytes(model.size_bytes)} disk</em>}{model.runtime_state !== "not_loaded" && <em className={model.ready ? "loaded" : ""}>{modelBadgeLabels[model.runtime_state]}</em>}</span>
                        </button>
                      );
                    })}
                  </div>
                  {selectedDraftModel && selectedDraftModel.provider === "gemini" && (
                    <div className="model-loader ready hosted">
                      <span className="model-loader-icon"><KeyRound size={17} /></span>
                      <div className="model-loader-copy">
                        <strong>{keyStatus?.configured ? "Ready when the key is valid" : "An API key is required"}</strong>
                        <span>Nothing is loaded for a hosted model: it answers as soon as the key works. Add the key below.</span>
                      </div>
                    </div>
                  )}

                  {selectedDraftModel && selectedDraftModel.provider !== "gemini" && (
                    <div className={`model-loader ${selectedRuntimeState}`}>
                      <span className="model-loader-icon"><Power size={17} /></span>
                      <div className="model-loader-copy">
                        <strong>{modelStateLabels[selectedRuntimeState]}</strong>
                        <span>{selectedRuntimeState === "profile_mismatch" ? "Something loaded this model with LM Studio's defaults, which put it on the integrated GPU. The first image would lose the Vulkan device, so reload it here first." : "Vision is prepared before document processing and timed separately. Large models use a CPU-safe profile on this device to avoid integrated-GPU memory failures."}</span>
                        {modelLoadReport && modelLoadReport.model === selectedDraftModel.id && (
                          <small>{modelLoadReport.profile === "compatibility" ? "CPU-safe" : "LM Studio default"} profile · {modelLoadReport.already_ready ? "Already ready" : `Load ${formatDuration(modelLoadReport.load_ms)} · ${modelLoadReport.warmup_mode === "vision" ? "Vision" : "Vision + schema"} warm-up ${formatDuration(modelLoadReport.warmup_ms)}${modelLoadReport.preparation_attempts > 1 ? ` · ${modelLoadReport.preparation_attempts} preparation attempts` : ""} · Total ${formatDuration(modelLoadReport.total_ms)}`}</small>
                        )}
                      </div>
                      <button className="model-load-button" disabled={!isConnected || selectedModelPreparing || selectedRuntimeState === "ready" || processState === "processing"} onClick={loadSelectedModel}>
                        {selectedModelPreparing ? <><LoaderCircle className="spin" size={14} /> {selectedRuntimeState === "warming_up" ? "Warming up…" : "Loading…"}</> : selectedRuntimeState === "ready" ? <><Check size={14} /> Ready</> : <><Power size={14} /> {selectedRuntimeState === "profile_mismatch" ? "Reload safely" : selectedRuntimeState === "loaded" || selectedRuntimeState === "error" ? "Warm up" : "Load & warm up"}</>}
                      </button>
                    </div>
                  )}
                  <div className="structured-output-note"><Braces size={15} /><div><strong>Structured output is enabled</strong><span>The backend sends a schema built from your entities with every request, in the shape each provider accepts. Nothing has to be configured in LM Studio or in Google AI Studio.</span></div></div>
                </div>

                <div className="settings-card">
                  <div className="settings-card-heading">
                    <span className="settings-card-icon"><KeyRound size={18} /></span>
                    <div><h3>Google Gemini</h3><p>Create a key in Google AI Studio. It is stored on this machine and never sent back to the browser.</p></div>
                    <span className={`connection-badge ${keyStatus?.configured ? "online" : ""}`}>
                      <CircleDot size={12} /> {keyStatus?.configured ? `Key ${keyStatus.hint}` : "No key"}
                    </span>
                  </div>

                  <label className="input-label" htmlFor="gemini-key">API key</label>
                  <div className="key-row">
                    <input
                      id="gemini-key"
                      className="text-input"
                      type="password"
                      autoComplete="off"
                      placeholder={keyStatus?.configured ? "Leave empty to keep the stored key" : "Paste your Google AI Studio key"}
                      value={geminiKey}
                      onChange={(event) => setGeminiKey(event.target.value)}
                    />
                    <button
                      className="secondary-button"
                      disabled={!keyStatus?.configured || verifying}
                      onClick={() => {
                        setVerifying(true);
                        setSettingsError(null);
                        void api.verifyGeminiKey()
                          .then(setKeyStatus)
                          .catch((cause) => setSettingsError(cause instanceof Error ? cause.message : String(cause)))
                          .finally(() => setVerifying(false));
                      }}
                    >
                      {verifying ? <LoaderCircle className="spin" size={14} /> : <ShieldCheck size={14} />} Verify
                    </button>
                    {keyStatus?.configured && (
                      <button
                        className="secondary-button danger"
                        onClick={() => {
                          void api.clearGeminiKey()
                            .then(() => api.geminiKeyStatus())
                            .then(setKeyStatus)
                            .catch((cause) => setSettingsError(cause instanceof Error ? cause.message : String(cause)));
                          setGeminiKey("");
                        }}
                      >
                        <Trash2 size={14} /> Remove
                      </button>
                    )}
                  </div>
                  <p className="field-help">
                    Saving with the field empty keeps the key already stored. The key is written to
                    backend/data/settings.json on this machine.
                  </p>
                  {keyStatus && keyStatus.verified_models.length > 0 && (
                    <p className="field-help good-note">
                      <Check size={12} /> The key can use: {keyStatus.verified_models.join(", ")}.
                    </p>
                  )}

                  <label className="input-label prompt-label" htmlFor="thinking-level">Thinking level</label>
                  <select
                    id="thinking-level"
                    className="text-input"
                    value={draftSettings.gemini.thinking_level}
                    onChange={(event) => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, thinking_level: event.target.value as AppSettings["gemini"]["thinking_level"] } })}
                  >
                    <option value="minimal">Minimal</option>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                  <p className="field-help">
                    Gemini 3 defaults to <code>high</code>, which an extraction rarely needs and always pays for.
                    Ignored by models without thinking, such as Flash Lite.
                  </p>

                  <p className="input-label prompt-label">Price per million tokens (USD)</p>
                  <div className="pricing-grid">
                    {Object.entries(draftSettings.gemini.pricing).map(([modelId, price]) => (
                      <div className="pricing-row" key={modelId}>
                        <code>{modelId}</code>
                        <label>
                          <span>Input</span>
                          <input
                            type="number" step="0.01" min="0"
                            value={price.input_per_million ?? ""}
                            onChange={(event) => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, pricing: { ...draftSettings.gemini.pricing, [modelId]: { ...price, input_per_million: event.target.value === "" ? null : Number(event.target.value) } } } })}
                          />
                        </label>
                        <label>
                          <span>Output</span>
                          <input
                            type="number" step="0.01" min="0"
                            value={price.output_per_million ?? ""}
                            onChange={(event) => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, pricing: { ...draftSettings.gemini.pricing, [modelId]: { ...price, output_per_million: event.target.value === "" ? null : Number(event.target.value) } } } })}
                          />
                        </label>
                      </div>
                    ))}
                  </div>
                  <p className="field-help">
                    Rates you can edit, checked on {draftSettings.gemini.pricing_checked_on}. They are not
                    read from Google: published prices change, and Gemini 3.7 Flash is already scheduled to
                    double on 1 January 2027. Thinking tokens are billed at the output rate.
                  </p>
                </div>

                <div className="settings-card">
                  <div className="settings-card-heading">
                    <span className="settings-card-icon"><Scissors size={18} /></span>
                    <div><h3>Single-call limit</h3><p>Control how many initial pages can be sent together in one extraction request.</p></div>
                  </div>
                  <div className="limit-grid single">
                    <label className="limit-field" htmlFor="max-pages">
                      <span>Maximum pages per extraction</span>
                      <input id="max-pages" type="number" min="1" max="100" step="1" value={pageLimitInput} onChange={(event) => { const value = event.target.value; setPageLimitInput(value); const parsed = Number(value); if (/^\d+$/.test(value) && parsed >= 1 && parsed <= 100) setDraftSettings({ ...draftSettings, max_pages_to_analyze: parsed }); }} onBlur={() => { if (!/^\d+$/.test(pageLimitInput) || Number(pageLimitInput) < 1 || Number(pageLimitInput) > 100) setPageLimitInput(String(draftSettings.max_pages_to_analyze)); }} />
                      <small>The app always sends pages 1–N in one model call; it never merges independent page extractions.</small>
                    </label>
                  </div>
                </div>

            <div className="settings-actions sticky-actions">
              <p><ShieldCheck size={14} /> Changes apply from the next processing run.</p>
              <button className="primary-button save-button" disabled={settingsState === "saving" || !settingsLoaded} onClick={saveSettings}>
                {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
                {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save settings"}
              </button>
            </div>
          </section>
        )}
      </section>
    </main>
  );
}
