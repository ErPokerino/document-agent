"use client";

import {
  AlertCircle,
  Braces,
  BrainCircuit,
  Cloud,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  LayoutDashboard,
  Library,
  SlidersHorizontal,
  Workflow,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { compactExtractorVersion, engineDetail } from "../lib/extraction-engine";
import { resolveBootstrap } from "../lib/bootstrap";
import { describeDataFlow } from "../lib/data-flow";
import { uploadsOnlyScans, usesModel } from "../lib/pipeline-steps";
import { formatHash, parseHash, type AppRoute, type AppView } from "../lib/route";
import { Datasets } from "./datasets/datasets";
import { Entities } from "./extraction/entities";
import { MasterData } from "./master-data/master-data";
import { Models } from "./models/models";
import { Lab } from "./lab/lab";
import { modelDisplayName, modelStatusLabel } from "../lib/format";
import { LanguageModels } from "./llm/llm";
import { Pipelines } from "./pipelines/pipeline";
import { Processors } from "./processors/processors";
import { Settings } from "./settings/settings";
import { SignInGate } from "./components/sign-in";
import { stepLabels } from "../lib/pipeline-editor";
import { validateSettingsDraft } from "../lib/validation";
import { Workspace, useWorkspace } from "./workspace/workspace";
import type {
  AppSettings,
  HealthStatus,
  ModelInfo,
  ModelLoadResponse,
  GeminiKeyStatus,
} from "../lib/types";

type View = AppView;
const sectionCopy: Record<View, { eyebrow: string; title: string }> = {
  workspace: { eyebrow: "Invoice extraction", title: "Document workspace" },
  extraction: { eyebrow: "What comes out of a document", title: "Extraction" },
  "master-data": { eyebrow: "Reference tables", title: "Master Data" },
  pipelines: { eyebrow: "How a document is processed", title: "Pipelines" },
  datasets: { eyebrow: "Ground truth", title: "Datasets" },
  lab: { eyebrow: "Extraction quality", title: "Lab" },
  models: { eyebrow: "Learned from labelled datasets", title: "Models" },
  llm: { eyebrow: "Where extraction runs", title: "LLM" },
  processors: { eyebrow: "Document AI resources", title: "Processors" },
  settings: { eyebrow: "Preferences", title: "Settings" },
};

export default function Home() {
  return (
    <SignInGate>
      <App />
    </SignInGate>
  );
}

function App() {
  // The server cannot see the hash, so the first render is the default route on
  // both sides; the address bar is read once the page is live. Reading it during
  // the first render made the browser's markup differ from the server's whenever
  // the page was opened on a section, and React threw the server render away.
  const [route, setRoute] = useState<AppRoute>(() => parseHash(""));
  const routeRef = useRef(route);
  const view = route.view;

  useEffect(() => {
    routeRef.current = route;
  }, [route]);

  function navigate(next: AppRoute) {
    const hash = formatHash(next);
    if (typeof window !== "undefined" && window.location.hash !== hash) window.location.hash = hash;
    setRoute(next);
  }

  function setView(nextView: View) {
    navigate({ ...routeRef.current, view: nextView });
  }

  useEffect(() => {
    function onHash() {
      const parsed = parseHash(window.location.hash);
      setRoute((current) => ({
        view: parsed.view,
        dataset: parsed.view === "datasets" ? parsed.dataset : current.dataset,
        evaluationId: parsed.view === "lab" ? parsed.evaluationId : current.evaluationId,
        filters: parsed.view === "lab" ? parsed.filters : current.filters,
      }));
    }
    window.addEventListener("hashchange", onHash);
    if (!window.location.hash) history.replaceState(null, "", "#/workspace");
    const opened = window.setTimeout(onHash, 0);
    return () => {
      window.clearTimeout(opened);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  // Null until the backend answers. There is deliberately no local default:
  // saving one would overwrite the stored prompts with frontend constants.
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draftSettings, setDraftSettings] = useState<AppSettings | null>(null);
  const [pipelineShape, setPipelineShape] = useState<string[]>([]);
  const [pipelineKinds, setPipelineKinds] = useState<string[]>([]);
  const [onlyScansUploaded, setOnlyScansUploaded] = useState(false);
  const [settingsState, setSettingsState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [modelsRefreshing, setModelsRefreshing] = useState(false);
  const [modelLoadState, setModelLoadState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [modelLoadReport, setModelLoadReport] = useState<ModelLoadResponse | null>(null);
  const [geminiKey, setGeminiKey] = useState("");
  const [keyStatus, setKeyStatus] = useState<GeminiKeyStatus | null>(null);
  const [verifying, setVerifying] = useState(false);

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
        setPipelineKinds(pipeline ? pipeline.steps.map((step) => step.kind) : []);
        setOnlyScansUploaded(pipeline ? uploadsOnlyScans(pipeline.steps) : false);
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
        const [discovered, stored] = await Promise.all([api.models(), api.settings()]);
        if (!active) return;
        setModels(discovered);
        // What is displayed converges on what the backend holds, whatever
        // wrote it. Only the shown state: `draftSettings` is the edit buffer
        // and belongs to whoever is typing in it.
        setSettings(stored);
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

  const settingsLoaded = settings !== null && draftSettings !== null;
  // Where documents actually go. Saying "local" while pages are being uploaded
  // to Google would be the worst kind of wrong copy.
  const usingHostedModel = settings?.provider === "gemini";
  // A model server holds its model; nothing on this machine has to be running.
  const usingModelServer = settings?.provider === "model_server";
  // Not only the model: a Document AI step uploads the page whatever answers
  // afterwards, so a pipeline with one is not local processing.
  const dataFlow = describeDataFlow(settings?.provider ?? "lm_studio", pipelineKinds, onlyScansUploaded);
  const configuredEntities = settings?.prompts.entities ?? [];
  const [engineResult, setEngineResult] = useState<{ settings: AppSettings; engine: import("../lib/types").ExtractionEngine | null } | null>(null);
  const extractionEngine = engineResult?.settings === settings ? engineResult?.engine : null;
  useEffect(() => {
    let current = true;
    if (settings) api.extractionEngine().then(engine => { if (current) setEngineResult({ settings, engine }); }).catch(() => { if (current) setEngineResult({ settings, engine: null }); });
    return () => { current = false; };
  }, [settings]);
  const activeModelName = modelDisplayName(settings?.model ?? "", models);
  const isConnected = health?.lm_studio === true;
  const activeModel = models.find((model) => model.id === settings?.model);
  const isModelReady = activeModel?.ready === true;
  // Not every pipeline asks a model anything. One that extracts with the Custom
  // Extractor never does, so nothing here should hold its run back over a model
  // it will not use — and nothing should describe it as having answered.
  //
  // Until the pipeline has been read the answer is assumed to be yes: on the
  // first paint that shows a gate which may not apply, where the other way
  // round would let a run start that then fails.
  const callsModel = pipelineKinds.length === 0 || usesModel(pipelineKinds);
  const needsLmStudio = callsModel && !usingHostedModel && !usingModelServer;
  const modelBlocks = callsModel && !isModelReady;
  const lmStudioBlocks = needsLmStudio && !isConnected;
  // The chip names the model this machine is set to. On a pipeline that never
  // calls it, "Model ready" is true and beside the point, and reading it as a
  // prerequisite is the mistake the rest of this block exists to prevent.
  const activeModelStatus = callsModel
    ? modelStatusLabel(settings?.model ?? "", activeModel)
    : "Not used by this pipeline";

  const workspace = useWorkspace({ modelBlocks });

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
      workspace.invalidateResult();
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
      workspace.invalidateResult();
    } catch (requestError) {
      setSettingsError(requestError instanceof Error ? requestError.message : "Model loading failed");
      setModelLoadState("error");
      setModels(await api.models().catch(() => models));
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark"><FileText size={18} strokeWidth={2.2} /></span>
          <div><strong>DocuFlow</strong><span>Document intelligence</span></div>
        </div>

        <nav className="nav-list" aria-label="Main navigation">
          <button className={`nav-item ${view === "workspace" ? "active" : ""}`} onClick={() => setView("workspace")} title={sectionCopy["workspace"].title}>
            <LayoutDashboard size={17} /> Workspace
          </button>
          <button className={`nav-item ${view === "extraction" ? "active" : ""}`} onClick={() => setView("extraction")} title={sectionCopy["extraction"].title}>
            <Braces size={17} /> Extraction
          </button>
          <button className={`nav-item ${view === "pipelines" ? "active" : ""}`} onClick={() => setView("pipelines")} title={sectionCopy["pipelines"].title}>
            <Workflow size={17} /> Pipelines
          </button>
          <button className={`nav-item ${view === "master-data" ? "active" : ""}`} onClick={() => setView("master-data")} title={sectionCopy["master-data"].title}>
            <Library size={17} /> Master Data
          </button>
          <button className={`nav-item ${view === "datasets" ? "active" : ""}`} onClick={() => setView("datasets")} title={sectionCopy["datasets"].title}>
            <Database size={17} /> Datasets
          </button>
          <button className={`nav-item ${view === "lab" ? "active" : ""}`} onClick={() => setView("lab")} title={sectionCopy["lab"].title}>
            <FlaskConical size={17} /> Lab
          </button>
          <button className={`nav-item ${view === "models" ? "active" : ""}`} onClick={() => setView("models")} title={sectionCopy["models"].title}>
            <BrainCircuit size={17} /> Models
          </button>
          <button className={`nav-item ${view === "llm" ? "active" : ""}`} onClick={() => setView("llm")} title={sectionCopy["llm"].title}>
            <Cpu size={17} /> LLM
          </button>
          <button className={`nav-item ${view === "processors" ? "active" : ""}`} onClick={() => setView("processors")} title={sectionCopy["processors"].title}><Cloud size={17}/> Processors</button>
          <button className={`nav-item ${view === "settings" ? "active" : ""}`} onClick={() => setView("settings")} title={sectionCopy["settings"].title}>
            <SlidersHorizontal size={17} /> Settings
          </button>
        </nav>

        <div className="sidebar-bottom">
          <div className={`local-status ${usingHostedModel ? (keyStatus?.configured ? "online" : "offline") : usingModelServer ? (isModelReady ? "online" : "offline") : isConnected ? "online" : "offline"}`}>
            <span className="status-dot" />
            <div>
              <strong>{usingHostedModel ? "Google Gemini" : usingModelServer ? "Model server" : "LM Studio"}</strong>
              <small>{usingHostedModel ? "Hosted API" : usingModelServer ? "Self-hosted model" : "Local inference"}</small>
            </div>
            <span className="status-pill">
              {usingHostedModel
                ? keyStatus?.configured ? "Key set" : "No key"
                : usingModelServer ? isModelReady ? "Serving" : "Not serving"
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
            <button className="model-chip" onClick={() => setView(pipelineKinds.includes("document_ai_extract") ? "pipelines" : "llm")} title={pipelineKinds.includes("document_ai_extract") ? [extractionEngine?.display_name, engineDetail({ model: pipelineKinds.some(kind => kind === "llm_extract" || kind === "supplier_rules") ? settings?.model || "Not used" : "Not used", steps: pipelineKinds, extraction_engine: extractionEngine ?? null }), "Choose the processor and version in Pipelines."].filter(Boolean).join("\n") : "Change model in LLM"}>
              <span className="model-icon"><Cpu size={15} /></span>
              <div><small>{pipelineKinds.includes("document_ai_extract") ? `Document AI · CE${extractionEngine?.additional_processors?.length ? ` +${extractionEngine.additional_processors.length}` : ""}` : activeModelStatus}</small><strong>{pipelineKinds.includes("document_ai_extract") ? engineResult?.settings !== settings ? "Reading version…" : compactExtractorVersion(extractionEngine?.version) : activeModelName}</strong></div>
              {!pipelineKinds.includes("document_ai_extract") && <span className={`connection-light ${(usingModelServer || isConnected) && isModelReady ? "online" : ""}`} />}
            </button>
          </div>
        </header>

        {view === "workspace" ? (
          <Workspace
            workspace={workspace}
            settings={settings}
            callsModel={callsModel}
            isModelReady={isModelReady}
            modelBlocks={modelBlocks}
            lmStudioBlocks={lmStudioBlocks}
            dataFlow={dataFlow}
            pipelineShape={pipelineShape}
            pipelineKinds={pipelineKinds}
            onOpenLlm={() => setView("llm")}
          />
        ) : !settings || !draftSettings ? (
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
        ) : view === "extraction" ? (
          <Entities
            draftSettings={draftSettings}
            setDraftSettings={setDraftSettings}
            onSave={saveSettings}
            settingsState={settingsState}
            settingsError={settingsError}
          />
        ) : view === "master-data" ? (
          <MasterData entities={configuredEntities} />
        ) : view === "pipelines" ? (
          <Pipelines
            draftSettings={draftSettings}
            entities={configuredEntities}
            onUse={usePipeline}
            onProcessors={() => setView("processors")}
            onModels={() => setView("models")}
          />
        ) : view === "processors" ? (
          <Processors draftSettings={draftSettings} setDraftSettings={setDraftSettings} onSave={saveSettings} settingsState={settingsState} settingsError={settingsError} onPipelines={() => setView("pipelines")}/>
        ) : view === "settings" ? (
          <Settings
            draftSettings={draftSettings}
            setDraftSettings={setDraftSettings}
            onSave={saveSettings}
            settingsState={settingsState}
            settingsError={settingsError}
          />
        ) : view === "datasets" ? (
          <Datasets
            savedEntities={configuredEntities}
            isModelReady={!callsModel || isModelReady}
            dataset={route.dataset}
            onDataset={(name) => navigate({ ...routeRef.current, view: "datasets", dataset: name })}
          />
        ) : view === "models" ? (
          <Models entities={configuredEntities} onPipelines={() => setView("pipelines")} />
        ) : view === "lab" ? (
          <Lab
            settings={settings}
            isModelReady={isModelReady}
            activeModel={activeModel}
            pipelineKinds={pipelineKinds}
            route={{ evaluationId: route.evaluationId, filters: route.filters }}
            onRoute={(next) => navigate({ ...routeRef.current, view: "lab", ...next })}
          />
        ) : (
          <LanguageModels
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
            connectionError={health?.lm_studio_error ?? null}
            processState={workspace.processState}
          />
        )}
      </section>
    </main>
  );
}
