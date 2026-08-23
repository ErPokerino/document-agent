"use client";

import {
  AlertCircle,
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
  History,
  LoaderCircle,
  Play,
  RefreshCw,
  Square,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api, apiUrls } from "../lib/api";
import { InfoHint } from "./info-hint";
import { formatUsd, totalCost } from "../lib/cost";
import { filterByName } from "../lib/document-filter";
import { accuracyClass, describeValue, percent, seconds } from "../lib/format";
import {
  distinctModels,
  distinctPipelines,
  emptyFilters,
  filterEvaluations,
  hasActiveFilters,
  type EvaluationFilters,
} from "../lib/run-filters";
import { runsToCsv } from "../lib/runs-csv";
import { stepLabel } from "../lib/pipeline-editor";
import { entitiesIn, scoreWithout } from "../lib/scoring-view";
import { nextSort, sortEvaluations, type Sort, type SortKey } from "../lib/run-sort";
import type { AppSettings, Dataset, Evaluation, EvaluationDetail, MetricTally } from "../lib/types";
import { DocumentPreview, type PreviewTarget } from "./document-preview";

type Props = {
  draftSettings: AppSettings;
  isModelReady: boolean;
};

/** Run the configured extraction over a dataset and score what comes back. */
export function Lab({ draftSettings, isModelReady }: Props) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [openEvaluation, setOpenEvaluation] = useState<EvaluationDetail | null>(null);
  const [filters, setFilters] = useState<EvaluationFilters>(emptyFilters);
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

  const running = evaluations.find((evaluation) => evaluation.status === "running") ?? null;
  const visibleEvaluations = sortEvaluations(
    filterEvaluations(evaluations, filters),
    sort.key,
    sort.direction,
  );

  function runCost(evaluation: Evaluation): number | null {
    return totalCost(
      {
        promptTokens: evaluation.prompt_tokens,
        completionTokens: evaluation.completion_tokens,
        ocrPages: evaluation.ocr_pages,
        layoutPages: evaluation.layout_pages,
      },
      draftSettings.gemini.pricing[evaluation.model],
      draftSettings.gcp,
    );
  }

  /** What you exported is what you were looking at: same rows, same order. */
  function downloadRunsCsv() {
    const csv = runsToCsv(visibleEvaluations, draftSettings, excluded);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `docuflow-runs-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function refreshEvaluations() {
    setEvaluations(await api.evaluations());
  }

  async function refreshValidatedRuns() {
    await api.runs(true);
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [nextDatasets, nextEvaluations] = await Promise.all([api.datasets(), api.evaluations()]);
        if (!active) return;
        setDatasets(nextDatasets);
        setEvaluations(nextEvaluations);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

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

  function toggleExpanded(name: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

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
          <span><Workflow size={13} /> Pipeline <strong>{draftSettings.pipeline}</strong></span>
          <span><Cpu size={13} /> Model <strong>{draftSettings.model}</strong></span>
          <InfoHint text="A run always uses the pipeline and model selected right now, and records both, so two runs can be compared afterwards." />
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
        {!isModelReady && <p className="field-help">Load and warm up the model in Models before running a test.</p>}
        {running && (
      <div className="run-progress">
        <LoaderCircle className="spin" size={15} />
        <span>
          {running.dataset} · {running.succeeded_documents} of {running.total_documents} documents
          {running.failed_documents > 0 && ` · ${running.failed_documents} failed`}
        </span>
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
      <label><span>Pipeline</span>
        <select value={filters.pipeline} onChange={(event) => setFilters({ ...filters, pipeline: event.target.value })}>
          <option value="">Any</option>
          {distinctPipelines(evaluations).map((name) => <option key={name} value={name}>{name}</option>)}
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
      <button
        className="secondary-button small"
        disabled={visibleEvaluations.length === 0}
        title="One row per run: pipeline, model, accuracy, timing, tokens, pages and cost"
        onClick={() => downloadRunsCsv()}
      >
        <Download size={13} /> Export {visibleEvaluations.length} runs
      </button>
      <button className="secondary-button small" disabled={!hasActiveFilters(filters)} onClick={() => setFilters(emptyFilters)}>
        <FilterX size={13} /> Clear
      </button>
        </div>

      <div className="score-without">
          <span>
            Score without
            <InfoHint text="Leaves these fields out of every accuracy on this page. Nothing stored changes: it answers how a run did on the rest, which is the fair question when one pipeline fills a field another does not." />
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
      <div className="models-empty"><AlertCircle size={18} /><span>No run matches these filters. {evaluations.length} hidden.</span></div>
        ) : (
      <div className="runs-table-wrap">
        <table className="runs-table">
          <thead>
            <tr>
              {([
                ["status", "Status", false],
                ["id", "Run", false],
                ["created_at", "Date", false],
                ["model", "Model", false],
                ["total_documents", "Docs", true],
                ["total_elapsed_ms", "Total time", true],
                ["max_pages", "Max pages", true],
                ["accuracy", "Accuracy", true],
              ] as [SortKey, string, boolean][]).map(([key, label, numeric]) => (
                <th key={key} className={numeric ? "numeric" : ""} aria-sort={sort.key === key ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
                  <button className="sort-button" onClick={() => setSort(nextSort(sort, key))}>
                    {label}
                    {sort.key === key && (sort.direction === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                  </button>
                </th>
              ))}
              <th className="numeric">Cost</th>
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
                <td><span className="model-tag">{evaluation.model}</span><small className="run-pipeline">{evaluation.pipeline}</small></td>
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
                <td className="numeric cost-cell">{formatUsd(runCost(evaluation))}</td>
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
        <a className="secondary-button small" href={apiUrls.evaluationCsv(openEvaluation.id)} download>
          <Download size={13} /> CSV
        </a>
        <button className="icon-button" aria-label="Close" onClick={() => setOpenEvaluation(null)}><X size={15} /></button>
      </div>

      <div className="run-tags">
        <span className="model-tag">{openEvaluation.model}</span>
        <span className="pipeline-tag">
          <Workflow size={11} /> {openEvaluation.pipeline}
        </span>
        {openEvaluation.steps.length > 0 && (
          <span className="steps-tag" title="The steps this run actually went through, in order">
            {openEvaluation.steps.map(stepLabel).join(" → ")}
          </span>
        )}
        <span className="pages-tag">{openEvaluation.max_pages || "?"} pages per extraction</span>
        <span className="pages-tag">{openEvaluation.prompts.entities.length} entities</span>
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
        {runCost(openEvaluation) !== null && (
          <span className="cost-tag" title="Derived from the token and page counts and the rates configured in Models, not from what Google billed">
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
            A retry reuses this run&apos;s prompts, model and page limit, so the result stays one experiment.
          </span>
          <button
            className="secondary-button"
            disabled={busy || !!running || !isModelReady}
            title={running ? "Another run is in progress" : !isModelReady ? "Load and warm up the model in Models first" : "Process the documents this run did not score"}
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
        {filterByName(openEvaluation.documents, runDocumentQuery).map((document) => {
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
                  </span>
                )}
                <button
                  className="icon-button"
                  aria-label={`Preview ${document.name}`}
                  title="Open the document"
                  onClick={() => setPreview({ dataset: openEvaluation.dataset, document: document.name })}
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
                      <th>Entity</th>
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
        })}
      </div>
        </div>
      )}
    

      <DocumentPreview target={preview} onClose={() => setPreview(null)} />
    </section>
  );
}
