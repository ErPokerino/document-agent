"use client";

import {
  AlertCircle,
  Braces,
  Check,
  CheckCircle2,
  CircleDot,
  Cpu,
  Eye,
  KeyRound,
  LoaderCircle,
  Power,
  RefreshCw,
  Save,
  Scissors,
  Server,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";

import { api } from "../lib/api";
import type { AppSettings, GeminiKeyStatus, ModelInfo, ModelLoadResponse, ModelRuntimeState } from "../lib/types";

export const modelStateLabels: Record<ModelRuntimeState, string> = {
  not_loaded: "Model not loaded",
  loaded: "Model in memory",
  loading: "Loading model",
  warming_up: "Warming up model",
  ready: "Model ready",
  error: "Model preparation failed",
  profile_mismatch: "Loaded with the wrong profile",
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

export function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

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
  pageLimitInput: string;
  setPageLimitInput: (value: string) => void;
  processState: string;
};

/** Which model answers, how it is reached, and what it costs to run. */
export function Models(props: Props) {
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
    pageLimitInput,
    setPageLimitInput,
    processState,
  } = props;

  const selectedDraftModel = models.find((model) => model.id === draftSettings.model);
  const selectedRuntimeState = selectedDraftModel?.runtime_state ?? "not_loaded";
  const selectedModelPreparing =
    selectedRuntimeState === "loading" || selectedRuntimeState === "warming_up" || modelLoadState === "loading";

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Cpu size={19} />
        <div><h2>Models</h2><p>Where extraction runs: a model in LM Studio on this machine, or the Gemini API.</p></div>
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
        <button className="primary-button save-button" disabled={settingsState === "saving" || !settingsLoaded} onClick={onSave}>
          {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
          {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save settings"}
        </button>
      </div>
    </section>
  );
}
