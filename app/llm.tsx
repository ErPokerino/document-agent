"use client";

import {
  AlertCircle,
  Braces,
  Check,
  CheckCircle2,
  CircleDot,
  Cloud,
  Cpu,
  Eye,
  FilterX,
  HardDrive,
  HelpCircle,
  KeyRound,
  LoaderCircle,
  Power,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  Type,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { InfoHint } from "./info-hint";
import { describeHost, describeRuntimeEngine } from "../lib/runtime-engine";
import { formatBytes, modelStateLabels } from "../lib/format";
import {
  filterModels,
  sizeBuckets,
  type RunsFilter,
  type SizeFilter,
  type VisionFilter,
} from "../lib/model-filter";
import type { AppSettings, GeminiKeyStatus, ModelInfo, ModelLoadResponse, ModelRuntimeState, RuntimeEngineInfo } from "../lib/types";

// What was actually applied, which is not always what was wanted: the part
// of the CPU-safe profile that holds a model's layers off the GPU is set
// through the LM Studio CLI, and a machine without it gets the rest.
const profileLabels: Record<ModelLoadResponse["profile"], string> = {
  compatibility: "CPU-safe",
  compatibility_partial: "CPU-safe without GPU offload (no lms CLI here)",
  standard: "DocuFlow standard",
};

export const modelBadgeLabels: Record<ModelRuntimeState, string> = {
  not_loaded: "Available",
  loaded: "In memory",
  loading: "Loading",
  warming_up: "Warming up",
  ready: "Ready",
  error: "Preparation failed",
  profile_mismatch: "Needs reload",
};

export function formatDuration(ms: number) {
  return `${(ms / 1000).toFixed(1)} s`;
}

type Props = {
  models: ModelInfo[];
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
  geminiKey: string;
  setGeminiKey: (key: string) => void;
  keyStatus: GeminiKeyStatus | null;
  setKeyStatus: (status: GeminiKeyStatus | null) => void;
  verifying: boolean;
  setVerifying: (value: boolean) => void;
  settingsError: string | null;
  setSettingsError: (message: string | null) => void;
  settingsState: "idle" | "saving" | "saved" | "error";
  settingsLoaded: boolean;
  onSave: () => void;
  loadSelectedModel: () => void;
  modelLoadState: "idle" | "loading" | "ready" | "error";
  modelLoadReport: ModelLoadResponse | null;
  setModelLoadState: (state: "idle" | "loading" | "ready" | "error") => void;
  setModelLoadReport: (report: ModelLoadResponse | null) => void;
  modelsRefreshing: boolean;
  isConnected: boolean;
  connectionError: string | null;
  processState: string;
};

/** Which language model answers, how it is reached, and what it costs to run.

    Named for what it holds. "Models" would cover the ML components a pipeline
    may call one day, which are a different thing configured elsewhere.
 */
export function LanguageModels(props: Props) {
  const {
    models,
    draftSettings,
    setDraftSettings,
    geminiKey,
    setGeminiKey,
    keyStatus,
    setKeyStatus,
    verifying,
    setVerifying,
    settingsError,
    setSettingsError,
    settingsState,
    settingsLoaded,
    onSave,
    loadSelectedModel,
    modelLoadState,
    modelLoadReport,
    setModelLoadState,
    setModelLoadReport,
    modelsRefreshing,
    isConnected,
    connectionError,
    processState,
  } = props;

  const [runsFilter, setRunsFilter] = useState<RunsFilter>("any");
  const [visionFilter, setVisionFilter] = useState<VisionFilter>("any");
  const [sizeFilter, setSizeFilter] = useState<SizeFilter>("any");
  // Which llama.cpp build LM Studio has selected. A machine-wide setting
  // changed from LM Studio itself, so it is read once rather than polled.
  const [runtimeEngine, setRuntimeEngine] = useState<RuntimeEngineInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .runtimeEngine()
      .then((info) => {
        if (!cancelled) setRuntimeEngine(info);
      })
      .catch(() => {
        // The engine is context, not a feature. Failing to read it leaves
        // the panel as it was rather than putting an error in front of it.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visibleModels = filterModels(models, {
    runs: runsFilter,
    vision: visionFilter,
    size: sizeFilter,
  });
  const filtered = visibleModels.length !== models.length;

  const selectedDraftModel = models.find((model) => model.id === draftSettings.model);
  const selectedRuntimeState = selectedDraftModel?.runtime_state ?? "not_loaded";
  const engineNote = selectedDraftModel
    ? describeRuntimeEngine(runtimeEngine, {
        vision: selectedDraftModel.vision,
        safeProfile: selectedDraftModel.requires_safe_profile,
      })
    : null;
  const hostNote = describeHost(runtimeEngine);
  // The load either failed just now, or LM Studio is holding the model in a
  // state it could not finish preparing. Either way there is a reason, and
  // the panel reporting the failure is where it belongs.
  const failureReason =
    (modelLoadState === "error" || selectedRuntimeState === "error") && settingsError
      ? settingsError
      : null;
  const selectedModelPreparing =
    selectedRuntimeState === "loading" || selectedRuntimeState === "warming_up" || modelLoadState === "loading";

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Cpu size={19} />
        <div><h2>LLM</h2><p>Which language model answers, and where it runs: LM Studio on this machine, or the Gemini API.</p></div>
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
        {/* Why nothing local is listed. The models list cannot carry this: with
            a Gemini key configured it is not empty, so its empty state never
            shows and the local half just quietly goes missing. */}
        {!isConnected && connectionError && (
          <p className="connection-problem">
            <AlertCircle size={14} />
            <span>{connectionError}</span>
          </p>
        )}
        {hostNote && (
          <p className="host-note">
            <Cpu size={13} />
            <span>{hostNote}<InfoHint text="Read from LM Studio on this machine, for the runtime it currently has selected. The budget is derived from the accelerator, not fixed in DocuFlow, so it follows the machine the app is installed on." /></span>
          </p>
        )}
      </div>

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Cpu size={18} /></span>
          <div><h3>Extraction model<InfoHint text="A pipeline that renders page images needs a model that can see. One that reads OCR text does not, and a text-only model is usually faster and cheaper." /></h3><p>Local models come from LM Studio, refreshed every 10 seconds. Hosted models run on Google&apos;s servers and need only an API key.</p></div>
          <span className="connection-badge"><RefreshCw className={modelsRefreshing ? "spin" : ""} size={12} /> Auto refresh</span>
        </div>

        <div className="model-filters">
          <label>
            <span>Runs</span>
            <select value={runsFilter} onChange={(event) => setRunsFilter(event.target.value as RunsFilter)}>
              <option value="any">Anywhere</option>
              <option value="local">On this machine</option>
              <option value="api">Through an API</option>
            </select>
          </label>
          <label>
            <span>Reads</span>
            <select value={visionFilter} onChange={(event) => setVisionFilter(event.target.value as VisionFilter)}>
              <option value="any">Images or text</option>
              <option value="vision">Page images</option>
              <option value="text">Text only</option>
            </select>
          </label>
          <label>
            <span>On disk</span>
            <select value={sizeFilter} onChange={(event) => setSizeFilter(event.target.value as SizeFilter)}>
              {sizeBuckets.map((bucket) => (
                <option key={bucket.value} value={bucket.value}>{bucket.label}</option>
              ))}
            </select>
          </label>
          {filtered && (
            <button className="link-button" onClick={() => { setRunsFilter("any"); setVisionFilter("any"); setSizeFilter("any"); }}>
              <FilterX size={13} /> Clear · {visibleModels.length} of {models.length}
            </button>
          )}
        </div>

        <div className="model-list">
          {models.length === 0 ? (
            <div className="models-empty"><AlertCircle size={18} /><span>{connectionError ?? "LM Studio answered, and has no models installed."}</span></div>
          ) : visibleModels.length === 0 ? (
            <div className="models-empty"><FilterX size={18} /><span>No model matches these filters.</span></div>
          ) : visibleModels.map((model) => {
            const selected = draftSettings?.model === model.id;
            return (
              <button key={model.id} className={`model-option ${selected ? "selected" : ""}`} onClick={() => { setDraftSettings({ ...draftSettings, model: model.id, provider: model.provider }); setModelLoadState("idle"); setModelLoadReport(null); }}>
                <span className="radio">{selected && <span />}</span>
                <span className={`model-option-icon ${model.provider === "gemini" ? "hosted" : "local"}`} title={model.provider === "gemini" ? "Runs on Google's servers" : "Runs on this machine"}>
                  {model.provider === "gemini" ? <Cloud size={17} /> : <HardDrive size={17} />}
                </span>
                <span className="model-option-copy"><strong>{model.name}</strong><small>{model.id}</small></span>
                <span className={`provider-tag ${model.provider}`}>{model.provider === "gemini" ? "Google API" : "Local"}</span>
                <span className={`capability-tag ${model.vision ? "vision" : "text"}`}>
                  {model.capabilities_known === false ? <><HelpCircle size={11} /> Capabilities unknown</> : model.vision ? <><Eye size={11} /> Vision</> : <><Type size={11} /> Text only</>}
                </span>
                <span className="model-specs">{model.parameters && <em>{model.parameters}</em>}{model.quantization && <em>{model.quantization}</em>}{model.size_bytes && <em>{formatBytes(model.size_bytes)} disk</em>}{model.context_length && <em>{model.context_length.toLocaleString()} context</em>}{model.parallel && <em>{model.parallel} parallel</em>}{model.runtime_state !== "not_loaded" && <em className={model.ready ? "loaded" : ""}>{modelBadgeLabels[model.runtime_state]}</em>}</span>
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
              {/* A failure is explained where it is reported. The reason used to
                  go to the banner at the top of the section, which is a long
                  way above the panel someone is looking at when it happens. */}
              <span>{failureReason
                ? failureReason
                : selectedRuntimeState === "profile_mismatch"
                ? selectedDraftModel.requires_safe_profile
                  ? "This model is loaded with a different context or concurrency profile. Reloading applies DocuFlow's reproducible settings and keeps its layers on the processor for this host."
                  : "This model is loaded with different context or concurrency settings. Reloading applies the same DocuFlow profile used on other PCs."
                : selectedDraftModel.vision
                  ? "Loading and warm-up are timed separately from document processing, and the vision path is prepared here rather than inside the first document's timer."
                  : "Loading and warm-up are timed separately from document processing. This model reads text only, so nothing is prepared for images."}</span>
              {engineNote && <small className="model-loader-engine">{engineNote}</small>}
              {modelLoadReport && modelLoadReport.model === selectedDraftModel.id && (
                <small>{profileLabels[modelLoadReport.profile]} profile · {modelLoadReport.already_ready ? "Already ready" : `Load ${formatDuration(modelLoadReport.load_ms)} · ${modelLoadReport.warmup_mode === "vision" ? "Vision" : "Vision + schema"} warm-up ${formatDuration(modelLoadReport.warmup_ms)}${modelLoadReport.preparation_attempts > 1 ? ` · ${modelLoadReport.preparation_attempts} preparation attempts` : ""} · Total ${formatDuration(modelLoadReport.total_ms)}`}</small>
              )}
            </div>
            <button className="model-load-button" disabled={!isConnected || selectedModelPreparing || selectedRuntimeState === "ready" || processState === "processing" || processState === "cancelling"} onClick={loadSelectedModel}>
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
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
        <p className="field-help">
          Gemini 3 defaults to <code>high</code>, which an extraction rarely needs and always pays for.
          Thinking tokens are billed at the output rate. Ignored by models without thinking, such as
          Flash Lite.
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

      <div className="settings-actions sticky-actions">
        <p><ShieldCheck size={14} /> Changes apply from the next processing run.</p>
        <button className="primary-button save-button" disabled={settingsState === "saving" || !settingsLoaded} onClick={onSave}>
          {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
          {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save settings"}
        </button>
      </div>
    </section>
  );
}
