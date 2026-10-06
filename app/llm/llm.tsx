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
  LoaderCircle,
  Power,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Type,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { InfoHint } from "../components/info-hint";
import { describeHost, describeRuntimeEngine } from "../../lib/runtime-engine";
import { formatBytes, modelStateLabels } from "../../lib/format";
import { checkFor, draftLocation, locationLabel, publisherOf, publishers, routeLabel, type Publisher } from "../../lib/hosted-providers";
import { CheckChip, HostedModelStatus, HostedProviderCards } from "./hosted-providers";
import {
  filterModels,
  isHostedProvider,
  sizeBuckets,
  type RunsFilter,
  type SizeFilter,
  type VisionFilter,
} from "../../lib/model-filter";
import type { AppSettings, GeminiKeyStatus, HostedModelCheck, ModelInfo, ModelLoadResponse, ModelRuntimeState, PublishedRate, RuntimeEngineInfo } from "../../lib/types";

// What was actually applied, which is not always what was wanted: the part
// of the CPU-safe profile that holds a model's layers off the GPU is set
// through the LM Studio CLI, and a machine without it gets the rest.
const profileLabels: Record<ModelLoadResponse["profile"], string> = {
  compatibility: "CPU-safe",
  compatibility_partial: "CPU-safe without GPU offload (no lms CLI here)",
  standard: "DocuFlow standard",
  server: "Model server",
};

const warmupLabels: Record<ModelLoadResponse["warmup_mode"], string> = {
  vision: "Vision",
  schema: "Schema",
  vision_and_schema: "Vision + schema",
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
  // False where this deployment runs no LM Studio: nothing to connect to.
  lmStudioEnabled: boolean;
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
    lmStudioEnabled,
    processState,
  } = props;
  const servedModels = models.filter((model) => model.provider === "model_server");
  // A deployment reaching Gemini through Vertex AI has no key to manage.
  const throughVertex = keyStatus?.access === "vertex";

  const [runsFilter, setRunsFilter] = useState<RunsFilter>(isHostedProvider(draftSettings.provider) ? "api" : "local");
  const [visionFilter, setVisionFilter] = useState<VisionFilter>("any");
  const [sizeFilter, setSizeFilter] = useState<SizeFilter>("any");
  // Which llama.cpp build LM Studio has selected. A machine-wide setting
  // changed from LM Studio itself, so it is read once rather than polled.
  const [runtimeEngine, setRuntimeEngine] = useState<RuntimeEngineInfo | null>(null);
  // What each hosted model answered when last verified, per location, and
  // Google's published rates for every hosted model. Both come from the backend.
  const [checks, setChecks] = useState<HostedModelCheck[]>([]);
  const [published, setPublished] = useState<PublishedRate[]>([]);
  const [verifyingPublisher, setVerifyingPublisher] = useState<Publisher | null>(null);

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
    // Context too: without them the cards say "Not verified" and show no rates.
    api.hostedChecks().then((value) => { if (!cancelled) setChecks(value); }).catch(() => {});
    api.publishedRates().then((value) => { if (!cancelled) setPublished(value); }).catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  /** Verify where the location on screen says, saved or not. */
  function verifyPublisher(publisher: Publisher) {
    setSettingsError(null);
    if (publisher === "google" && !throughVertex) {
      setVerifying(true);
      void api.verifyGeminiKey()
        .then(setKeyStatus)
        .catch((cause) => setSettingsError(cause instanceof Error ? cause.message : String(cause)))
        .finally(() => setVerifying(false));
      return;
    }
    const location = draftLocation(draftSettings, publisher, keyStatus);
    if (!location) return;
    setVerifyingPublisher(publisher);
    void api.verifyHosted({ publisher, location: location as "eu" | "us" | "global" })
      .then(setChecks)
      .catch((cause) => setSettingsError(cause instanceof Error ? cause.message : String(cause)))
      .finally(() => setVerifyingPublisher(null));
  }
  const verifyingHosted: Publisher | null = verifying && !throughVertex ? "google" : verifyingPublisher;

  const visibleModels = filterModels(models, {
    runs: runsFilter,
    vision: visionFilter,
    size: runsFilter === "local" ? sizeFilter : "any",
  });
  const scopedModels = filterModels(models, { runs: runsFilter });
  const filtered = visionFilter !== "any" || (runsFilter === "local" && sizeFilter !== "any");

  const selectedDraftModel = models.find((model) => model.id === draftSettings.model);
  const selectedRuntimeState = selectedDraftModel?.runtime_state ?? "not_loaded";
  const selectedPublisher = selectedDraftModel ? publisherOf(selectedDraftModel) : null;
  const selectedLocation = selectedPublisher ? draftLocation(draftSettings, selectedPublisher, keyStatus) : null;
  const engineNote = selectedDraftModel?.provider === "lm_studio"
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

  const renderModel = (model: ModelInfo) => {
    const selected = draftSettings?.model === model.id;
    const hosted = isHostedProvider(model.provider);
    const publisher = publisherOf(model);
    // Where it would run is the publisher's location, shown on the group.
    const hostedCheck = publisher ? checkFor(checks, model.id, draftLocation(draftSettings, publisher, keyStatus)) : undefined;
    return (
      <button key={model.id} className={`model-option ${selected ? "selected" : ""}`} onClick={() => { setDraftSettings({ ...draftSettings, model: model.id, provider: model.provider }); setModelLoadState("idle"); setModelLoadReport(null); }}>
        <span className="radio">{selected && <span />}</span>
        <span className={`model-option-icon ${hosted ? "hosted" : "local"}`} title={hosted ? "Runs on Google Cloud" : model.provider === "model_server" ? "Runs on the model server of this deployment" : "Runs on this machine"}>
          {hosted ? <Cloud size={17} /> : model.provider === "model_server" ? <Server size={17} /> : <HardDrive size={17} />}
        </span>
        <span className="model-option-copy"><strong>{model.name}</strong><small>{model.id}</small></span>
        <span className={`provider-tag ${model.provider}`}>{hosted ? routeLabel(model, keyStatus) : model.provider === "model_server" ? "Model server" : "Local"}</span>
        <span className={`capability-tag ${model.vision ? "vision" : "text"}`}>
          {model.capabilities_known === false ? <><HelpCircle size={11} /> Capabilities unknown</> : model.vision ? <><Eye size={11} /> Vision</> : <><Type size={11} /> Text only</>}
        </span>
        <span className="model-specs">{model.preview && <em>Preview</em>}{model.parameters && <em>{model.parameters}</em>}{model.quantization && <em>{model.quantization}</em>}{model.size_bytes && <em>{formatBytes(model.size_bytes)} disk</em>}{model.context_length && <em>{model.context_length.toLocaleString()} context</em>}{model.parallel && <em>{model.parallel} parallel</em>}{hosted ? <CheckChip check={hostedCheck} /> : model.runtime_state !== "not_loaded" && <em className={model.ready ? "loaded" : ""}>{modelBadgeLabels[model.runtime_state]}</em>}</span>
      </button>
    );
  };

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Cpu size={19} />
        <div><h2>LLM</h2><p>Which language model answers, and where it runs: {lmStudioEnabled ? "LM Studio on this machine" : "the model server of this deployment"}, or a hosted model on Google Cloud: Gemini, Claude or Grok.</p></div>
      </div>

      <div className="resource-tabs" aria-label="Model location">
        <button aria-pressed={runsFilter === "local"} onClick={() => setRunsFilter("local")}>{lmStudioEnabled ? "Local" : "Self-hosted"} <small>{filterModels(models, { runs: "local" }).length}</small></button>
        <button aria-pressed={runsFilter === "api"} onClick={() => setRunsFilter("api")}>API <small>{filterModels(models, { runs: "api" }).length}</small></button>
      </div>
      <p className="resource-selection">Selected model: <strong>{selectedDraftModel?.name || draftSettings.model || "None"}</strong> · {selectedDraftModel && selectedPublisher ? `${routeLabel(selectedDraftModel, keyStatus)}${selectedLocation ? `, ${locationLabel(selectedLocation)}` : ""}` : draftSettings.provider === "model_server" ? "Model server" : "Local"}. Model changes apply when saved.</p>

      {settingsError && <div className="alert error-alert"><AlertCircle size={17} />{settingsError}</div>}

      <div className="settings-card" hidden={runsFilter !== "local" || lmStudioEnabled}>
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Server size={18} /></span>
          <div><h3>Model server</h3><p>Open models served for this deployment, behind an OpenAI-compatible API. It holds one model at a time: Load &amp; warm up loads the one selected and unloads the previous, as LM Studio does locally.</p></div>
          <span className={`connection-badge ${servedModels.length ? "online" : ""}`}><CircleDot size={12} /> {servedModels.length ? `${servedModels.length} models · ${servedModels.filter((model) => model.ready).length} loaded` : "Not answering"}</span>
        </div>
        {!servedModels.length && (
          <p className="connection-problem">
            <AlertCircle size={14} />
            <span>The model server listed no models. A server that has scaled to zero answers once its model has loaded, which takes a while.</span>
          </p>
        )}
      </div>

      <div className="settings-card" hidden={runsFilter !== "local" || !lmStudioEnabled}>
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
          <div><h3>Extraction model<InfoHint text="Image-based model extraction needs a vision model. OCR text can be sent to a text or vision model. A Custom Extractor pipeline may not call an LLM." /></h3><p>{runsFilter === "api" ? "Hosted models run on Google Cloud, grouped by who makes them. Nothing is loaded: Verify asks the selected one for a token where it would run." : `${lmStudioEnabled ? "Local models come from LM Studio" : "Self-hosted models come from the model server"}, refreshed every 10 seconds.`}</p></div>
          <span className="connection-badge"><RefreshCw className={modelsRefreshing ? "spin" : ""} size={12} /> Auto refresh</span>
        </div>

        <div className="model-filters">
          <label>
            <span>Reads</span>
            <select value={visionFilter} onChange={(event) => setVisionFilter(event.target.value as VisionFilter)}>
              <option value="any">Images or text</option>
              <option value="vision">Page images</option>
              <option value="text">Text only</option>
            </select>
          </label>
          <label hidden={runsFilter !== "local"}>
            <span>On disk</span>
            <select value={sizeFilter} onChange={(event) => setSizeFilter(event.target.value as SizeFilter)}>
              {sizeBuckets.map((bucket) => (
                <option key={bucket.value} value={bucket.value}>{bucket.label}</option>
              ))}
            </select>
          </label>
          {filtered && (
            <button className="link-button" onClick={() => { setVisionFilter("any"); setSizeFilter("any"); }}>
              <FilterX size={13} /> Clear · {visibleModels.length} of {scopedModels.length}
            </button>
          )}
        </div>

        <div className="model-list">
          {scopedModels.length === 0 ? (
            <div className="models-empty"><AlertCircle size={18} /><span>{runsFilter === "local" ? (lmStudioEnabled ? connectionError ?? "LM Studio answered, and has no models installed." : "The model server listed no models.") : "No API models are available."}</span></div>
          ) : visibleModels.length === 0 ? (
            <div className="models-empty"><FilterX size={18} /><span>No model matches these filters.</span></div>
          ) : runsFilter === "api" ? publishers.map((publisher) => {
            const group = visibleModels.filter((model) => publisherOf(model) === publisher.id);
            if (!group.length) return null;
            const location = draftLocation(draftSettings, publisher.id, keyStatus);
            return (
              <div className="model-group" key={publisher.id}>
                <p className="model-group-heading">{publisher.family} <span>{publisher.company} · {routeLabel(group[0], keyStatus)}{location ? ` · ${locationLabel(location)}` : ""}</span></p>
                {group.map(renderModel)}
              </div>
            );
          }) : visibleModels.map(renderModel)}
        </div>
        {runsFilter === "api" && selectedDraftModel && selectedPublisher && (
          <HostedModelStatus
            model={selectedDraftModel}
            settings={draftSettings}
            keyStatus={keyStatus}
            checks={checks}
            verifying={verifyingHosted === selectedPublisher}
            onVerify={() => verifyPublisher(selectedPublisher)}
          />
        )}
        {runsFilter === "local" && selectedDraftModel && !isHostedProvider(selectedDraftModel.provider) && (
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
                <small>{profileLabels[modelLoadReport.profile]} profile · {modelLoadReport.already_ready ? "Already ready" : `Load ${formatDuration(modelLoadReport.load_ms)} · ${warmupLabels[modelLoadReport.warmup_mode]} warm-up ${formatDuration(modelLoadReport.warmup_ms)}${modelLoadReport.preparation_attempts > 1 ? ` · ${modelLoadReport.preparation_attempts} preparation attempts` : ""} · Total ${formatDuration(modelLoadReport.total_ms)}`}</small>
              )}
            </div>
            <button className="model-load-button" disabled={!(selectedDraftModel.provider === "model_server" ? servedModels.length > 0 : isConnected) || selectedModelPreparing || selectedRuntimeState === "ready" || processState === "processing" || processState === "cancelling"} onClick={loadSelectedModel}>
              {selectedModelPreparing ? <><LoaderCircle className="spin" size={14} /> {selectedRuntimeState === "warming_up" ? "Warming up…" : "Loading…"}</> : selectedRuntimeState === "ready" ? <><Check size={14} /> Ready</> : <><Power size={14} /> {selectedRuntimeState === "profile_mismatch" ? "Reload safely" : selectedRuntimeState === "loaded" || selectedRuntimeState === "error" ? "Warm up" : "Load & warm up"}</>}
            </button>
          </div>
        )}
        <div className="structured-output-note"><Braces size={15} /><div><strong>Structured output is enabled</strong><span>The backend sends a schema built from your fields with every request, in the shape each provider accepts. Nothing has to be configured in LM Studio or in Google AI Studio.</span></div></div>
      </div>

      {runsFilter === "api" && (
        <HostedProviderCards
          models={models}
          draftSettings={draftSettings}
          setDraftSettings={setDraftSettings}
          keyStatus={keyStatus}
          setKeyStatus={setKeyStatus}
          geminiKey={geminiKey}
          setGeminiKey={setGeminiKey}
          setSettingsError={setSettingsError}
          checks={checks}
          verifyingPublisher={verifyingHosted}
          onVerify={verifyPublisher}
          published={published}
          selectedPublisher={selectedPublisher}
        />
      )}

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
