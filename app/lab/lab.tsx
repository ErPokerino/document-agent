"use client";

import {
  AlertCircle,
  BarChart3,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Check,
  ChevronDown,
  ChevronRight,
  Cpu,
  Download,
  Eye,
  EyeOff,
  FilterX,
  FlaskConical,
  Grid3x3,
  History,
  Info,
  LoaderCircle,
  Play,
  RefreshCw,
  Square,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api, apiUrls } from "../../lib/api";
import { engineLabel, engineDetail, versionLabel } from "../../lib/extraction-engine";
import { Analytics } from "./analytics";
import { ClassificationPanel } from "./classification-panel";
import { ExperimentBuilder } from "./experiment-builder";
import { ExperimentsView } from "./experiment-view";
import { MethodsPanel } from "./methods-panel";
import { InfoHint } from "../components/info-hint";
import { RunFiltersBar } from "./run-filters-bar";
import { formatUsd, totalCost } from "../../lib/cost";
import { filterByName } from "../../lib/document-filter";
import { accuracyClass, describeValue, percent, seconds } from "../../lib/format";
import { labRunTarget } from "../../lib/lab-target";
import { useLatest } from "../../lib/latest";
import { isPdfTextFallback, usesModel } from "../../lib/pipeline-steps";
import {
  emptyFilters,
  filterEvaluations,
  hiddenRunsNote,
  type EvaluationFilters,
} from "../../lib/run-filters";
import { runsToCsv } from "../../lib/runs-csv";
import { progressLabel, stepLabel } from "../../lib/pipeline-editor";
import { runWarning } from "../../lib/run-warning";
import { entitiesIn, scoreWithout } from "../../lib/scoring-view";
import { nextSort, sortEvaluations, type Sort, type SortKey } from "../../lib/run-sort";
import type {
  AppSettings,
  Dataset,
  Evaluation,
  EvaluationDetail,
  Experiment,
  MetricTally,
  ModelExecutionProfile,
  ModelInfo,
} from "../../lib/types";
import { DocumentPreview, type PreviewTarget } from "../components/document-preview";

type LabRoute = { evaluationId: number | null; filters: EvaluationFilters };

type Props = {
  settings: AppSettings;
  isModelReady: boolean;
  activeModel: ModelInfo | undefined;
  pipelineKinds: string[];
  route: LabRoute;
  onRoute: (next: LabRoute) => void;
};

function executionProfileLabel(profile: ModelExecutionProfile): string {
  if (profile.provider === "gemini") {
    return `hosted profile · temperature ${profile.temperature}${profile.thinking_level ? ` · thinking ${profile.thinking_level}` : ""}`;
  }
  return `${profile.profile} profile${profile.context_length ? ` · ${profile.context_length.toLocaleString()} context` : ""}${profile.seed !== null ? ` · seed ${profile.seed}` : ""}`;
}

/** Run the configured extraction over a dataset and score what comes back. */
export function Lab({ settings, isModelReady, activeModel, pipelineKinds, route, onRoute }: Props) {
  // A pipeline that never asks a model anything runs the same whatever is
  // loaded, so waiting for one would be a delay that buys nothing.
  const modelBlocks = usesModel(pipelineKinds) && !isModelReady;
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [loadedRun, setLoadedRun] = useState<EvaluationDetail | null>(null);
  const openEvaluation = loadedRun && loadedRun.id === route.evaluationId ? loadedRun : null;
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [engine, setEngine] = useState<import("../../lib/types").ExtractionEngine | null>(null);
  useEffect(() => {
    let current = true;
    api.extractionEngine().then(value => { if (current) setEngine(value); }).catch(() => { if (current) setEngine(null); });
    return () => { current = false; };
  }, [settings]);
  const filters = route.filters;
  // Two ways of reading the same runs. Both were on one page and it grew
  // taller than anything anyone would scroll.
  const [view, setView] = useState<"runs" | "analytics" | "experiments">("runs");
  // One configuration, or a grid of them: the same card starts either.
  const [mode, setMode] = useState<"single" | "experiment">("single");
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedExperiment, setSelectedExperiment] = useState<number | null>(null);
  const [sort, setSort] = useState<Sort>({ key: "id", direction: "desc" });
  // Scoring a run again without a field, in the view only: the stored run
  // is what happened, and this is a question about it.
  const [excluded, setExcluded] = useState<string[]>([]);
  const [runDocumentQuery, setRunDocumentQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [confirmingRun, setConfirmingRun] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewTarget | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Off unless chosen for this run: a Lab run measures time and pages, and a
  // reused reading costs neither.
  const [reuseReadings, setReuseReadings] = useState(false);
  const listRequests = useLatest();
  const detailRequests = useLatest();

  const running = evaluations.find((evaluation) => evaluation.status === "running") ?? null;
  const runningExperiment = experiments.find((experiment) => experiment.status === "running") ?? null;
  const reportError = useCallback((message: string) => setError(message), []);
  // Reads this machine's own history rather than assuming a cost, so it
  // still tells the truth on a machine this one knows nothing about.
  const runTarget = labRunTarget(settings, activeModel, usesModel(pipelineKinds));
  const runNote = runWarning(activeModel, pipelineKinds, evaluations, runTarget.pipeline);
  const visibleEvaluations = sortEvaluations(
    filterEvaluations(evaluations, filters),
    sort.key,
    sort.direction,
    runCost,
  );
  const hiddenNote = hiddenRunsNote(evaluations, visibleEvaluations);

  const pageCount = Math.max(1, Math.ceil(visibleEvaluations.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pageRows = visibleEvaluations.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  function runCost(evaluation: Evaluation): number | null {
    return totalCost(
      {
        promptTokens: evaluation.prompt_tokens,
        completionTokens: evaluation.completion_tokens,
        ocrPages: evaluation.ocr_pages,
        layoutPages: evaluation.layout_pages,
        customExtractorPages: evaluation.custom_extractor_pages,
        customExtractorUsed: evaluation.steps.includes("document_ai_extract"),
        modelBillable: evaluation.provider === "gemini",
        usageComplete: evaluation.usage_complete,
      },
      settings.gemini.pricing[evaluation.model],
      settings.gcp,
    );
  }

  /** What you exported is what you were looking at: same rows, same order. */
  function downloadRunsCsv() {
    const csv = runsToCsv(visibleEvaluations, settings, excluded);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `docuflow-runs-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function refreshEvaluations() {
    const isCurrent = listRequests.begin();
    const next = await api.evaluations();
    if (isCurrent()) setEvaluations(next);
  }

  async function refreshValidatedRuns() {
    await api.runs(true);
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [nextDatasets, nextEvaluations, nextExperiments] = await Promise.all([api.datasets(), api.evaluations(), api.experiments()]);
        if (!active) return;
        setDatasets(nextDatasets);
        setEvaluations(nextEvaluations);
        setExperiments(nextExperiments);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  // Between two cells an experiment is loading a model and no run is in
  // flight, so the experiment is polled on its own.
  useEffect(() => {
    if (!runningExperiment) return;
    const timer = window.setInterval(() => {
      void api.experiments().then(setExperiments).catch(() => undefined);
      void api.evaluations().then(setEvaluations).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [runningExperiment]);

  async function refreshExperiments() {
    setExperiments(await api.experiments());
    setEvaluations(await api.evaluations());
  }

  // A test run is many model calls; poll while one is in flight.
  useEffect(() => {
    if (!running) return;
    const runningId = running.id;
    const openId = openEvaluation?.id;
    const timer = window.setInterval(() => {
      const listIsCurrent = listRequests.begin();
      void api.evaluations()
        .then((next) => { if (listIsCurrent()) setEvaluations(next); })
        .catch(() => undefined);
      if (openId === runningId) {
        const detailIsCurrent = detailRequests.begin();
        void api.evaluation(runningId)
          .then((detail) => { if (detailIsCurrent()) setLoadedRun(detail); })
          .catch(() => undefined);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [running, openEvaluation?.id, listRequests, detailRequests]);
  function toggleExpanded(name: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function publish(evaluationId: number | null, nextFilters: EvaluationFilters = filters) {
    if (
      evaluationId === route.evaluationId
      && JSON.stringify(nextFilters) === JSON.stringify(route.filters)
    ) return;
    onRoute({ evaluationId, filters: nextFilters });
  }

  function openRun(evaluationId: number) {
    publish(evaluationId);
  }

  function closeRun() {
    publish(null);
  }

  // The address bar is what opens a run. A click only writes the hash, and
  // the back button writes it too, so both arrive here.
  useEffect(() => {
    if (route.evaluationId === null) {
      detailRequests.invalidate();
      return;
    }
    const isCurrent = detailRequests.begin();
    void api.evaluation(route.evaluationId)
      .then((detail) => {
        if (!isCurrent()) return;
        setExpanded(new Set());
        setRunDocumentQuery("");
        setLoadedRun(detail);
      })
      .catch((cause) => {
        if (!isCurrent()) return;
        setError(cause instanceof Error ? cause.message : String(cause));
      });
  }, [route.evaluationId, detailRequests]);

  async function refreshOpenRun(evaluationId: number) {
    const isCurrent = detailRequests.begin();
    const detail = await api.evaluation(evaluationId);
    if (isCurrent()) setLoadedRun(detail);
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

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <FlaskConical size={19} />
        <div><h2>Lab</h2><p>Run the current configuration over a dataset and see what it gets right.</p></div>
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
      <span className="settings-card-icon"><FlaskConical size={18} /></span>
      <div><h3>Run a test</h3><p>Every labelled document in the dataset is extracted with the saved prompts and scored.</p></div>
        </div>

        <div className="run-target">
          <span><Workflow size={13} /> Pipeline <strong>{runTarget.pipeline}</strong></span>
          <span><Cpu size={13} /> Extraction engine <strong title={engine?.version ? `Version: ${engine.version}${engine.base_model ? ` · Base model: ${engine.base_model}` : ""}` : undefined}>{pipelineKinds.includes("document_ai_extract") ? engine?.display_name || "Custom Extractor" : runTarget.modelName}</strong>{pipelineKinds.includes("document_ai_extract") && <small>{engine?.version ? versionLabel(engine.version) : "Version unavailable"}{usesModel(pipelineKinds) ? ` · Additional LLM: ${runTarget.modelName}` : ""}</small>}</span>
          <InfoHint text="A run records the pipeline and its execution profile. The selected model is recorded only when the pipeline can call it." />
        </div>

        <div className="segmented lab-mode" role="tablist" aria-label="What to run">
          <button type="button" role="tab" aria-selected={mode === "single"} className={mode === "single" ? "active" : ""} onClick={() => setMode("single")}>
            One configuration
          </button>
          <button type="button" role="tab" aria-selected={mode === "experiment"} className={mode === "experiment" ? "active" : ""} onClick={() => setMode("experiment")}>
            <Grid3x3 size={13} /> Experiment
          </button>
          <InfoHint text="An experiment runs several pipelines, each with several models, over one dataset — one ordinary run per cell — and compares them on the documents every cell scored, with confidence intervals." />
        </div>

        {mode === "experiment" ? (
          <ExperimentBuilder
            datasets={datasets}
            dataset={selectedDataset}
            onDataset={setSelectedDataset}
            busy={busy}
            running={Boolean(running || runningExperiment)}
            onError={reportError}
            onStarted={(experiment) => {
              setSelectedExperiment(experiment.id);
              setView("experiments");
              void refreshExperiments().catch(() => undefined);
            }}
          />
        ) : (<>
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
        <button className="primary-button" disabled={!selectedDataset || busy || modelBlocks || Boolean(runningExperiment)} onClick={() => guard(async () => { await api.startEvaluation(selectedDataset!, reuseReadings); await refreshEvaluations(); await refreshValidatedRuns(); })}>
          <Play size={14} /> Run test
        </button>
      )}
        </div>
        <label className="run-option">
          <input type="checkbox" checked={reuseReadings} disabled={!!running} onChange={(event) => setReuseReadings(event.target.checked)} />
          <span>Reuse stored Document AI readings</span>
          <InfoHint text="OCR and Layout Parser readings from earlier runs are read back instead of sent again, when the step names a pinned processor version. Time and pages are then not what the pipeline costs, so Analytics leaves this run out of its time and cost figures. Readings are stored by every run either way." />
        </label>
        {modelBlocks && <p className="field-help">Load and warm up the model in LLM before running a test.</p>}
        </>)}
        {runningExperiment && (
          <p className="field-help">
            Experiment <button type="button" className="link-button" onClick={() => { setSelectedExperiment(runningExperiment.id); setView("experiments"); }}>{runningExperiment.name}</button> is running.
            Cancelling the run in progress cancels the whole experiment.
          </p>
        )}
        {runNote && (
          <div className="alert warning-alert" role="status">
            <Info size={17} />
            <span>{runNote}</span>
          </div>
        )}
        {running && (
      <div className="run-progress">
        <LoaderCircle className="spin" size={15} />
        <span>
          {running.dataset} · {running.succeeded_documents} of {running.total_documents} documents
          {running.current_step ? ` · ${progressLabel(running.current_step)}` : ""}
          {running.failed_documents > 0 && ` · ${running.failed_documents} failed`}
        </span>
        <span className="run-progress-bar"><i style={{ width: `${(running.completed_documents / Math.max(running.total_documents, 1)) * 100}%` }} /></span>
      </div>
        )}
        <p className="field-help">Workspace processing is unavailable while a Lab run is active.</p>
      </div>

      <div className="settings-tabs lab-tabs">
        <button type="button" className={view === "runs" ? "active" : ""} onClick={() => setView("runs")}>
          <History size={14} /> Past runs <span>{visibleEvaluations.length}</span>
        </button>
        <button type="button" className={view === "analytics" ? "active" : ""} onClick={() => setView("analytics")}>
          <BarChart3 size={14} /> Analytics
        </button>
        <button type="button" className={view === "experiments" ? "active" : ""} onClick={() => setView("experiments")}>
          <Grid3x3 size={14} /> Experiments <span>{experiments.length}</span>
        </button>
      </div>

      {view === "experiments" ? (
        <div className="settings-card">
          <div className="settings-card-heading">
            <span className="settings-card-icon"><Grid3x3 size={18} /></span>
            <div>
              <h3>Experiments</h3>
              <p>Pipelines down the side, models across the top. Every cell is an ordinary run, also listed in Past runs; open one by clicking it.</p>
            </div>
          </div>
          <ExperimentsView
            experiments={experiments}
            selected={selectedExperiment}
            onSelect={setSelectedExperiment}
            onOpenRun={(evaluationId) => openRun(evaluationId)}
            onChanged={refreshExperiments}
            costOf={runCost}
            onError={reportError}
          />
        </div>
      ) : (

      <div className="settings-card">
        <div className="settings-card-heading">
      <span className="settings-card-icon">{view === "runs" ? <History size={18} /> : <BarChart3 size={18} />}</span>
      <div>
        <h3>{view === "runs" ? "Past runs" : "Analytics"}</h3>
        <p>{view === "runs"
          ? "Each run remembers the prompts, full pipeline and model execution profile it used."
          : "Approaches compared over the runs these filters leave in view."}</p>
      </div>
        </div>

        <RunFiltersBar evaluations={evaluations} filters={filters} setFilters={value => { setPage(1); publish(route.evaluationId, value); }}>
          {view === "runs" && <button
            type="button"
            className="secondary-button small"
            disabled={visibleEvaluations.length === 0}
            title="One row per run: pipeline, model, where it ran, accuracy, timing, tokens, pages and cost"
            onClick={() => downloadRunsCsv()}
          >
            <Download size={13} /> Export {visibleEvaluations.length} runs
          </button>}
        </RunFiltersBar>

        {hiddenNote && (
          <div className="hidden-runs-note" role="status">
            <Info size={14} />
            <span>{hiddenNote}</span>
            <button type="button" className="link-button" onClick={() => { setPage(1); publish(route.evaluationId, emptyFilters); }}>Show all runs</button>
          </div>
        )}

        {view === "runs" ? (<>
      <div className="score-without">
          <span>
            Score without
            <InfoHint text="Exclude selected fields from the scores displayed in Past runs and its export. Stored scores, accuracy filters and Analytics are unchanged." />
          </span>
          {entitiesIn(evaluations).map((entity) => {
            const off = excluded.includes(entity);
            return (
              <button
                key={entity}
                className={`entity-toggle ${off ? "off" : ""}`}
                aria-pressed={off}
                onClick={() =>
                  setExcluded(off ? excluded.filter((name) => name !== entity) : [...excluded, entity])
                }
              >
                {off ? <EyeOff size={12} /> : <Eye size={12} />} {entity}
              </button>
            );
          })}
          {excluded.length > 0 && (
            <button className="link-button" onClick={() => setExcluded([])}>Score with everything</button>
          )}
        </div>

        {evaluations.length === 0 ? (
      <div className="models-empty"><AlertCircle size={18} /><span>No test has been run yet.</span></div>
        ) : visibleEvaluations.length === 0 ? (
      <div className="models-empty"><AlertCircle size={18} /><span>No run matches these filters.</span></div>
        ) : (
      <>

      <div className="runs-table-wrap">
        <table className="runs-table">
          <thead>
            <tr>
              {([
                ["status", "Status", false],
                ["id", "Run", false],
                ["created_at", "Date", false],
                ["model", "Extraction engine", false],
                ["total_documents", "Docs", true],
                ["total_elapsed_ms", "Total time", true],
                ["max_pages", "Max pages", true],
                ["accuracy", "Accuracy", true],
                ["cost", "Cost", true],
              ] as [SortKey, string, boolean][]).map(([key, label, numeric]) => (
                <th key={key} className={numeric ? "numeric" : ""} aria-sort={sort.key === key ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
                  <button className="sort-button" onClick={() => { setSort(nextSort(sort, key)); setPage(1); }}>
                    {label}
                    {sort.key === key && (sort.direction === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                  </button>
                </th>
              ))}
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {pageRows.map((evaluation) => (
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
                <td><span className="model-tag engine-tag" title={engineDetail(evaluation)}>{engineLabel(evaluation)}</span><small className="run-pipeline">{evaluation.pipeline}</small></td>
                <td className="numeric">
                  {evaluation.succeeded_documents}/{evaluation.total_documents}
                  {evaluation.failed_documents > 0 && <small className="poor">{evaluation.failed_documents} failed</small>}
                </td>
                <td className="numeric">{seconds(evaluation.total_elapsed_ms)}<small>{seconds(evaluation.average_elapsed_ms)} avg</small></td>
                <td className="numeric">{evaluation.max_pages || "—"}</td>
                <td className={`numeric accuracy-cell ${accuracyClass(scoreWithout(evaluation.metrics, excluded).accuracy)}`}>
                  {percent(scoreWithout(evaluation.metrics, excluded).accuracy)}
                  <small>
                    {scoreWithout(evaluation.metrics, excluded).matched}/
                    {scoreWithout(evaluation.metrics, excluded).total}
                  </small>
                </td>
                <td className="numeric cost-cell" title={runCost(evaluation) === null ? "A complete estimate is unavailable: usage or configured rates are missing." : "Estimated API cost at the configured rates"}>{formatUsd(runCost(evaluation))}</td>
                <td className="row-actions" onClick={(event) => event.stopPropagation()}>
                  {confirmingRun === evaluation.id ? (
                    <span className="row-confirm compact">
                      <button className="secondary-button small ghost" onClick={() => setConfirmingRun(null)}>Cancel</button>
                      <button
                        className="secondary-button small danger"
                        disabled={busy}
                        onClick={() => guard(async () => {
                          await api.deleteEvaluation(evaluation.id);
                          if (openEvaluation?.id === evaluation.id) closeRun();
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
      <nav className="run-pagination" aria-label="Past runs pages">
        <span>{(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, visibleEvaluations.length)} of {visibleEvaluations.length} runs</span>
        <label>Rows <select aria-label="Runs per page" value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setPage(1); }}>{[10, 25, 50].map(size => <option key={size}>{size}</option>)}</select></label>
        <button className="secondary-button small" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</button>
        <label>Page <select aria-label="Past runs page" value={currentPage} onChange={event => setPage(Number(event.target.value))}>{Array.from({ length: pageCount }, (_, i) => <option key={i + 1}>{i + 1}</option>)}</select> of {pageCount}</label>
        <button className="secondary-button small" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>Next</button>
      </nav>
      </>
        )}
        </>) : (
          <Analytics evaluations={visibleEvaluations} costOf={runCost} />
        )}
      </div>
      )}

      {openEvaluation && (
        <div className="settings-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon"><CheckCircle2 size={18} /></span>
        <div>
          <h3>Run #{openEvaluation.id} · {openEvaluation.dataset}</h3>
          <p>{openEvaluation.succeeded_documents} of {openEvaluation.total_documents} documents scored · {seconds(openEvaluation.total_elapsed_ms)} in total · {seconds(openEvaluation.average_elapsed_ms)} per document</p>
        </div>
        <a className="secondary-button small" href={apiUrls.evaluationCsv(openEvaluation.id)} download>
          <Download size={13} /> CSV
        </a>
        <button className="icon-button" aria-label="Close" onClick={closeRun}><X size={15} /></button>
      </div>

      <div className="run-tags">
        <span className="model-tag engine-tag">{engineLabel(openEvaluation)}</span><span className="engine-detail">{engineDetail(openEvaluation)}</span>
        <span className="pipeline-tag">
          <Workflow size={11} /> {openEvaluation.pipeline}
        </span>
        {openEvaluation.steps.length > 0 && (
          <span className="steps-tag" title="The steps this run actually went through, in order">
            {openEvaluation.steps.map(stepLabel).join(" → ")}
          </span>
        )}
        <span className="pages-tag">{openEvaluation.max_pages || "?"} pages per extraction</span>
        <span className="pages-tag">{openEvaluation.prompts.entities.length} fields</span>
        {openEvaluation.fingerprint && (
          <span className="pages-tag" title="Documents, labels, prompts, pipeline, model profile, register and supplier rules">
            {openEvaluation.fingerprint.slice(0, 8)}
          </span>
        )}
        {openEvaluation.execution_profile && (
          <span className="pages-tag" title="The model controls recorded when this run started">
            {executionProfileLabel(openEvaluation.execution_profile)}
          </span>
        )}
        {openEvaluation.prompt_tokens > 0 && (
          <span className="pages-tag">
            {openEvaluation.prompt_tokens.toLocaleString()} in / {openEvaluation.completion_tokens.toLocaleString()} out tokens
          </span>
        )}
        {openEvaluation.ocr_pages + openEvaluation.layout_pages > 0 && (
          <span className="pages-tag">
            {openEvaluation.ocr_pages > 0 && `${openEvaluation.ocr_pages} OCR`}
            {openEvaluation.ocr_pages > 0 && openEvaluation.layout_pages > 0 && " / "}
            {openEvaluation.layout_pages > 0 && `${openEvaluation.layout_pages} layout`} pages
          </span>
        )}
        {(openEvaluation.custom_extractor_pages ?? 0) > 0 && (
          <span className="pages-tag">{openEvaluation.custom_extractor_pages} Custom Extractor pages</span>
        )}
        {openEvaluation.reuse_readings && (
          <span className="pages-tag" title="Pages read back from stored readings were not sent to Google, billed, or waited for">
            Reused readings · {openEvaluation.cached_pages} pages not sent
          </span>
        )}
        {runCost(openEvaluation) === null && (
          <span className="pages-tag">Cost unavailable · usage or rates incomplete</span>
        )}
        {runCost(openEvaluation) !== null && (
          <span className="cost-tag" title="Derived from the token and page counts and the rates configured in LLM, not from what Google billed">
            {formatUsd(runCost(openEvaluation))}
          </span>
        )}
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
            {openEvaluation.has_register_snapshot
              ? " A retry uses the original PDFs, labels, prompts, pipeline, model profile, page limit, register and supplier rules."
              : openEvaluation.has_dataset_snapshot
                ? " A retry uses the original PDFs, labels, prompts, pipeline, model profile and page limit. This run did not record the register or the supplier rules, so today's are used."
                : " This older run has no input snapshot and cannot be retried."}
          </span>
          <button
            className="secondary-button"
            disabled={busy || !!running || !openEvaluation.has_dataset_snapshot || (usesModel(openEvaluation.steps) && !isModelReady)}
            title={!openEvaluation.has_dataset_snapshot ? "Original PDFs and labels are unavailable for this run" : running ? "Another run is in progress" : "Process the documents this run did not score"}
            onClick={() => guard(async () => {
              await api.retryEvaluation(openEvaluation.id);
              await refreshEvaluations();
              await refreshOpenRun(openEvaluation.id);
            })}
          >
            <RefreshCw size={14} /> Retry {openEvaluation.failed_documents + openEvaluation.pending_documents} documents
          </button>
        </div>
      )}

      <div className="metric-grid">
        {tallyRows("Accuracy per field", openEvaluation.metrics.per_entity)}
        {tallyRows("How often each confidence level was right", openEvaluation.metrics.per_confidence)}
      </div>

      {(openEvaluation.methods ?? []).length > 0 && (
        <MethodsPanel evaluationId={openEvaluation.id} methods={openEvaluation.methods ?? []} metrics={openEvaluation.metrics} />
      )}

      {(openEvaluation.classification ?? []).map((report) => <ClassificationPanel report={report} key={report.entity} />)}

      {openEvaluation.documents.length > 1 && (
        <div className="name-filter">
          <input
            placeholder="Filter by file name"
            value={runDocumentQuery}
            onChange={(event) => setRunDocumentQuery(event.target.value)}
            aria-label="Filter run documents by file name"
          />
          <small>{filterByName(openEvaluation.documents, runDocumentQuery).length} of {openEvaluation.documents.length}</small>
          {runDocumentQuery && (
            <button className="secondary-button small ghost" onClick={() => setRunDocumentQuery("")}>
              <FilterX size={13} /> Clear
            </button>
          )}
        </div>
      )}

      <div className="document-results">
        {(() => {
          const ocrStandsIn = (openEvaluation.pipeline_definition?.steps ?? []).some(isPdfTextFallback);
          return filterByName(openEvaluation.documents, runDocumentQuery).map((document) => {
          const correct = document.items.filter((item) => item.matched).length;
          const isOpen = expanded.has(document.name);
          return (
            <div className={`document-result ${isOpen ? "expanded" : ""}`} key={document.name}>
              <div className="document-result-head">
                <button className="document-toggle" aria-expanded={isOpen} onClick={() => toggleExpanded(document.name)}>
                  {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <strong>{document.name}</strong>
                </button>
                {document.status === "failed" ? (
                  <span className="status-tag failed">failed</span>
                ) : (
                  <span className="document-summary">
                    <span className={correct === document.items.length ? "good" : "poor"}>{correct}/{document.items.length}</span>
                    <small>correct</small>
                    <small className="document-time">{seconds(document.elapsed_ms)}</small>
                    {ocrStandsIn && (document.ocr_pages ?? 0) > 0 && (
                      <small className="document-time" title="Read PDF text found no text in this PDF, so the OCR step read it">Read by OCR</small>
                    )}
                  </span>
                )}
                <button
                  className="icon-button"
                  aria-label={`Preview ${document.name}`}
                  title="Open the document"
                  onClick={() => setPreview({ dataset: openEvaluation.dataset, document: document.name, evaluationId: openEvaluation.has_dataset_snapshot ? openEvaluation.id : undefined })}
                >
                  <Eye size={15} />
                </button>
              </div>

              {document.error && <p className="field-warning"><AlertCircle size={11} /> {document.error}</p>}

              {isOpen && document.items.length > 0 && (
                <table className="mismatch-table">
                  <thead>
                    <tr>
                      <th aria-label="Result" />
                      <th>Field</th>
                      <th>Expected</th>
                      <th>Got</th>
                      <th>Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {document.items.map((item) => (
                      <tr key={item.entity} className={item.matched ? "matched" : ""}>
                        <td className="result-cell">{item.matched ? <Check size={13} /> : <X size={13} />}</td>
                        <td className="mismatch-entity">{item.entity}</td>
                        <td>{item.matched ? <span className="same-as-got">—</span> : <code className="expected">{describeValue(item.expected)}</code>}</td>
                        <td><code className={item.matched ? "correct" : "actual"}>{describeValue(item.actual)}</code></td>
                        <td><span className={`confidence-pill ${item.confidence}`}><i /> {item.confidence}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          );
        });
        })()}
      </div>
        </div>
      )}
    

      <DocumentPreview target={preview} onClose={() => setPreview(null)} />
    </section>
  );
}
