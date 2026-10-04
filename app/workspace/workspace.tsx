"use client";

import {
  AlertCircle,
  Check,
  ChevronRight,
  Cloud,
  Download,
  ExternalLink,
  Eye,
  FileJson,
  FileText,
  LoaderCircle,
  Pencil,
  RotateCcw,
  ScanSearch,
  Scissors,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { ChangeEvent, DragEvent, Fragment, KeyboardEvent, useEffect, useRef, useState } from "react";

import { api } from "../../lib/api";
import type { DataFlow } from "../../lib/data-flow";
import { formatBytes, formatLabels } from "../../lib/format";
import { CategoryOptions, categoryListId } from "../components/category-options";
import { progressLabel } from "../../lib/pipeline-editor";
import { buildReviewedExport } from "../../lib/review";
import type { AppSettings, Confidence, EntityDefinition, ExtractionResponse } from "../../lib/types";
import { PageHighlight } from "../components/page-highlight";

export type ProcessState = "idle" | "ready" | "processing" | "cancelling" | "complete" | "error";

const confidenceLabels: Record<Confidence, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

function prettyName(name: string) {
  return name.replaceAll("_", " ").replace(/^./, (character) => character.toUpperCase());
}

/**
 * The document being reviewed, and everything done to it.
 *
 * Held by the shell rather than by the Workspace view, so a document stays
 * loaded while another section is open.
 */
export function useWorkspace({ modelBlocks }: { modelBlocks: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [processState, setProcessState] = useState<ProcessState>("idle");
  const [result, setResult] = useState<ExtractionResponse | null>(null);
  const [editableValues, setEditableValues] = useState<Record<string, string>>({});
  const [editedFields, setEditedFields] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [reviewState, setReviewState] = useState<"idle" | "saving" | "saved">("idle");
  const previewUrlRef = useRef<string | null>(null);
  const extractionControllerRef = useRef<AbortController | null>(null);
  const extractionCancelledRef = useRef(false);

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  function clearResult() {
    setResult(null);
    setEditableValues({});
    setEditedFields(new Set());
  }

  function selectFile(selected: File | null) {
    setError(null);
    clearResult();
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

  function resetDocument() {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setPreviewUrl(null);
    setFile(null);
    clearResult();
    setError(null);
    setProcessState("idle");
  }

  /** The configuration changed, so a result produced under the old one is gone. */
  function invalidateResult() {
    clearResult();
    if (file) setProcessState("ready");
  }

  async function processDocument() {
    if (!file) return;
    if (modelBlocks) {
      setError("The active model is not ready. Open LLM and use Load & warm up first.");
      return;
    }
    setProcessState("processing");
    setError(null);
    clearResult();
    extractionCancelledRef.current = false;
    const controller = new AbortController();
    extractionControllerRef.current = controller;
    try {
      const extraction = await api.extract(file, controller.signal);
      if (extractionCancelledRef.current) return;
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
      if (extractionCancelledRef.current || controller.signal.aborted) {
        setProcessState("ready");
      } else {
        setError(requestError instanceof Error ? requestError.message : "Processing failed");
        setProcessState("error");
      }
    } finally {
      if (extractionControllerRef.current === controller) extractionControllerRef.current = null;
    }
  }

  async function cancelDocumentProcessing() {
    extractionCancelledRef.current = true;
    setProcessState("cancelling");
    setError(null);
    try {
      await api.cancelExtraction();
    } catch (requestError) {
      // A request may finish in the instant between the click and the cancel
      // endpoint. In that case the extraction promise remains authoritative.
      if (!(requestError instanceof Error && requestError.message.includes("No document"))) {
        setError(requestError instanceof Error ? requestError.message : "Cancellation failed");
      }
    } finally {
      extractionControllerRef.current?.abort();
      extractionControllerRef.current = null;
      setProcessState("ready");
    }
  }

  function downloadJson(entities: EntityDefinition[]) {
    if (!result) return;
    const reviewedData = buildReviewedExport(entities, result.data, editableValues, editedFields);
    const blob = new Blob([JSON.stringify(reviewedData, null, 2)], { type: "application/json" });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `${result.filename.replace(/\.pdf$/i, "")}.json`;
    anchor.click();
    URL.revokeObjectURL(href);
  }

  async function markReviewed(entities: EntityDefinition[]) {
    if (!result?.run_id) return;
    setReviewState("saving");
    setError(null);
    try {
      // Every field is sent, not only the edited ones: a run where the model
      // was right about everything is the most useful ground truth there is.
      const reviewed = buildReviewedExport(entities, result.data, editableValues, editedFields);
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

  return {
    file,
    previewUrl,
    processState,
    result,
    editableValues,
    editedFields,
    error,
    setError,
    reviewState,
    selectFile,
    resetDocument,
    invalidateResult,
    processDocument,
    cancelDocumentProcessing,
    downloadJson,
    markReviewed,
    updateReviewValue,
    revertReviewValue,
  };
}

export type WorkspaceState = ReturnType<typeof useWorkspace>;

type Props = {
  workspace: WorkspaceState;
  settings: AppSettings | null;
  callsModel: boolean;
  isModelReady: boolean;
  modelBlocks: boolean;
  lmStudioBlocks: boolean;
  dataFlow: DataFlow;
  pipelineShape: string[];
  pipelineKinds: string[];
  onOpenLlm: () => void;
};

/** Upload one invoice, run the pipeline in use over it, and review what came back. */
export function Workspace({
  workspace,
  settings,
  callsModel,
  isModelReady,
  modelBlocks,
  lmStudioBlocks,
  dataFlow,
  pipelineShape,
  pipelineKinds,
  onOpenLlm,
}: Props) {
  const {
    file,
    previewUrl,
    processState,
    result,
    editableValues,
    editedFields,
    error,
    setError,
    reviewState,
  } = workspace;
  // Which field the reader is pointing at, so the list and the page image
  // can highlight the same one from either side.
  const [locatedField, setLocatedField] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());
  const [ackRun, setAckRun] = useState<number | null>(null);
  const [polledStep, setPolledStep] = useState<string | null>(null);
  const fieldRefs = useRef<Record<string, HTMLInputElement | null>>({});
  // The preview shows the document or the values found on it, in the same
  // place. Two copies of one PDF down the page was the first attempt.
  const [previewMode, setPreviewMode] = useState<"document" | "highlights">("highlights");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const configuredEntities = settings?.prompts.entities ?? [];
  // The strip is numbered as it is walked, so dropping a step that never runs
  // does not leave a gap in the numbering.
  const firstStepNumber = callsModel ? 2 : 1;
  const unresolvedWarningCount = result
    ? Object.entries(result.data).filter(([name, field]) => field.warning && !editedFields.has(name) && !acknowledged.has(name)).length
    : 0;

  const runId = result?.run_id ?? null;
  if (ackRun !== runId) {
    setAckRun(runId);
    setAcknowledged(new Set());
  }
  const activeStep = processState === "processing" ? polledStep : null;

  // Lab's poll reports documents. A step changes inside one document, so the
  // strip asks on its own while this document is being processed.
  useEffect(() => {
    if (processState !== "processing") return;
    let current = true;
    const timer = window.setInterval(() => {
      void api.activity()
        .then((activity) => { if (current) setPolledStep(activity.step); })
        .catch(() => undefined);
    }, 500);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [processState]);

  function focusField(name: string) {
    setLocatedField(name);
    fieldRefs.current[name]?.focus();
  }

  function moveField(delta: number) {
    const names = configuredEntities.map((entity) => entity.name);
    if (!names.length) return;
    const index = locatedField ? names.indexOf(locatedField) : -1;
    const next = names[Math.min(names.length - 1, Math.max(0, index + delta))];
    focusField(next);
  }

  function onReviewKey(event: KeyboardEvent<HTMLInputElement>) {
    const typing = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement;
    const down = event.key === "ArrowDown" || (!typing && event.key === "j");
    const up = event.key === "ArrowUp" || (!typing && event.key === "k");
    if (down || up) {
      event.preventDefault();
      moveField(down ? 1 : -1);
      return;
    }
    if (event.key === "Enter" && locatedField) {
      event.preventDefault();
      const name = locatedField;
      setAcknowledged((current) => new Set(current).add(name));
      moveField(1);
      return;
    }
    if (event.key === "Escape" && locatedField) {
      event.preventDefault();
      const name = locatedField;
      if (editedFields.has(name)) workspace.revertReviewValue(name);
      setAcknowledged((current) => {
        const next = new Set(current);
        next.delete(name);
        return next;
      });
    }
  }
  const canHighlight = Boolean(result?.run_id) && (result?.locations.length ?? 0) > 0;

  function handleFileInput(event: ChangeEvent<HTMLInputElement>) {
    workspace.selectFile(event.target.files?.[0] ?? null);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    workspace.selectFile(event.dataTransfer.files?.[0] ?? null);
  }

  function resetDocument() {
    workspace.resetDocument();
    if (fileInput.current) fileInput.current.value = "";
  }

  const extractionPanel = (
    <section className={`schema-panel review-schema ${processState === "processing" || processState === "cancelling" ? "processing" : ""}`}>
      <div className="panel-heading">
        <div><h2>Extracted data</h2></div>
        <span className={`result-badge ${unresolvedWarningCount ? "warning" : processState}`}>
          {(processState === "processing" || processState === "cancelling") && <LoaderCircle className="spin" size={10} />}
          {processState === "complete" && unresolvedWarningCount === 0 && <Check size={10} />}
          {unresolvedWarningCount > 0 && <AlertCircle size={10} />}
          {unresolvedWarningCount > 0 ? "Review needed" : processState === "complete" ? "Complete" : processState === "cancelling" ? "Stopping" : processState === "processing" ? (activeStep ? progressLabel(activeStep) : "Processing") : "Waiting"}
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
            <div
              className={`field-row ${field?.warning && !edited && !acknowledged.has(entity.name) ? "has-warning" : ""} ${locatedField === entity.name ? "located" : ""}`}
              key={entity.name}
              onFocus={() => setLocatedField(entity.name)}
            >
              <div className="field-meta"><span>{prettyName(entity.name)}</span><code>{entity.name}</code></div>
              <div className={`field-value ${editableValue ? "populated" : ""}`}>
                {field ? (
                  <div className="editable-value">
                    <input
                      ref={(node) => { fieldRefs.current[entity.name] = node; }}
                      aria-label={`Edit ${prettyName(entity.name)}`}
                      onKeyDown={onReviewKey}
                      type={inputType}
                      step={entity.format === "integer" ? "1" : entity.format === "decimal" ? "any" : undefined}
                      maxLength={entity.format === "currency" ? 3 : undefined}
                      list={entity.format === "category" ? categoryListId(entity) : undefined}
                      placeholder="Enter value"
                      value={editableValue}
                      onChange={(event) => workspace.updateReviewValue(entity, event.target.value)}
                    />
                    <div className="value-controls">
                      <span className={`confidence-pill ${field.confidence}`} title={field.score === null || field.score === undefined ? "Original extraction confidence" : field.evidence ? `Similarity ${field.score.toFixed(2)} to the nearest labelled document` : `Match quality: ${field.score.toFixed(2)} similarity to the register`}><i /> {confidenceLabels[field.confidence]}{field.score !== null && field.score !== undefined && <em>{field.score.toFixed(2)}</em>}</span>
                      {edited && <span className="manual-pill"><Pencil size={9} /> Edited</span>}
                      {edited && <button className="revert-value" onClick={() => workspace.revertReviewValue(entity.name)} aria-label={`Revert ${prettyName(entity.name)}`} title="Restore extracted value"><RotateCcw size={11} /></button>}
                    </div>
                    {field.warning && !edited && <span className="field-warning"><AlertCircle size={11} /> {field.warning}</span>}
                    {field.evidence && !edited && <span className="field-evidence">{field.evidence}</span>}
                    {(field.candidates?.length ?? 0) > 1 && !edited && (
                      <span className="field-evidence" title="What each step proposed, in the order the steps ran">
                        {field.candidates!.map((candidate) => `${candidate.method}: ${candidate.value ?? "—"}`).join(" · ")}
                      </span>
                    )}
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

      <CategoryOptions entities={configuredEntities} />

      <div className="confidence-legend">
        {/* Who judged it depends on the pipeline: a model rates its own
            answers, while the Custom Extractor returns a number it computed. */}
        <span>{callsModel ? "Model-estimated confidence" : "Processor-reported confidence"}</span>
        <div><i className="high" /> High <i className="medium" /> Medium <i className="low" /> Low</div>
      </div>

      <div className="schema-footer">
        <span><FileJson size={13} /> Dynamic JSON Schema</span>
        <button className="export-button" disabled={!result?.run_id || reviewState === "saving"} onClick={() => workspace.markReviewed(configuredEntities)} title="Store these values as verified, so this document can become ground truth in Datasets">
          {reviewState === "saved" ? <><Check size={14} /> Saved as verified</> : <><ShieldCheck size={14} /> Mark as reviewed</>}
        </button>
        <button className="export-button" disabled={!result} onClick={() => workspace.downloadJson(configuredEntities)}><Download size={14} /> Export JSON</button>
      </div>
    </section>
  );

  return (
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
              <button type="button" className="primary-button" onClick={() => fileInput.current?.click()}>Select PDF</button>
              <small>Maximum 20 MB · Large files follow the configured page limit</small>
            </div>
            <input ref={fileInput} type="file" accept="application/pdf,.pdf" onChange={handleFileInput} hidden />
            <div className={`privacy-note ${dataFlow.leavesTheMachine ? "hosted" : ""}`}>{dataFlow.leavesTheMachine ? <Cloud size={16} /> : <ShieldCheck size={16} />}<p><strong>{dataFlow.heading}</strong> {dataFlow.detail}</p></div>
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
            <div className={`session-privacy ${dataFlow.leavesTheMachine ? "hosted" : ""}`}>{dataFlow.leavesTheMachine ? <Cloud size={15} /> : <ShieldCheck size={15} />}<span>{dataFlow.heading}</span></div>
            <div className="session-actions">
              {processState === "processing" || processState === "cancelling" ? (
                <button className="secondary-button session-process danger" disabled={processState === "cancelling"} onClick={workspace.cancelDocumentProcessing}>
                  {processState === "cancelling" ? <><LoaderCircle className="spin" size={15} /> Stopping…</> : <><Square size={14} /> Cancel</>}
                </button>
              ) : processState === "complete" ? (
                <button className="secondary-button session-process" disabled={modelBlocks} onClick={workspace.processDocument}><RotateCcw size={15} /> Process again</button>
              ) : (
                <button className="primary-button session-process" disabled={lmStudioBlocks || modelBlocks} onClick={workspace.processDocument}>
                  <><Sparkles size={16} /> Analyze invoice</>
                </button>
              )}
              <button className="icon-button" disabled={processState === "processing" || processState === "cancelling"} onClick={resetDocument} aria-label="Remove document"><Trash2 size={16} /></button>
            </div>
            {lmStudioBlocks && <small className="session-warning">Start LM Studio to process this document</small>}
            {!lmStudioBlocks && modelBlocks && <button className="session-warning action" onClick={onOpenLlm}>Prepare the active model in LLM before processing</button>}
          </section>
          <div className="review-grid">
            {previewUrl && (
              <section className="pdf-preview-panel">
                <div className="preview-toolbar">
                  <div><Eye size={15} /><span>Document preview</span></div>
                  <div className="preview-actions">
                    {canHighlight && (
                      <div className="preview-modes" role="group" aria-label="What to show">
                        <button
                          type="button"
                          className={previewMode === "document" ? "active" : ""}
                          onClick={() => setPreviewMode("document")}
                        >
                          Document
                        </button>
                        <button
                          type="button"
                          className={previewMode === "highlights" ? "active" : ""}
                          onClick={() => setPreviewMode("highlights")}
                        >
                          <ScanSearch size={12} /> {result!.locations.length} located
                        </button>
                      </div>
                    )}
                    {result && <span className="processed-badge">Model pages {result.processing.first_processed_page}–{result.processing.last_processed_page}</span>}
                    <a href={previewUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open</a>
                  </div>
                </div>
                {canHighlight && previewMode === "highlights" ? (
                  <PageHighlight
                    runId={result!.run_id!}
                    locations={result!.locations}
                    active={locatedField}
                    onActive={focusField}
                  />
                ) : (
                  <iframe src={previewUrl} title={`Preview of ${file.name}`} />
                )}
              </section>
            )}
            {extractionPanel}
          </div>
        </div>
      )}

      <footer className="pipeline-strip">
        <span>{settings?.pipeline ?? "Current pipeline"}</span>
        {callsModel && (
          <>
            <div className={`pipeline-step ${isModelReady ? "done" : "active"}`}><b>{isModelReady ? <Check size={10} /> : "1"}</b> {isModelReady ? "Model ready" : "Model not ready"}</div>
            <ChevronRight size={13} />
          </>
        )}
        <div className={`pipeline-step ${file ? "done" : ""}`}><b>{file ? <Check size={10} /> : firstStepNumber}</b> PDF input</div>
        {pipelineShape.map((label, index) => {
          const activeIndex = pipelineKinds.indexOf(activeStep ?? "");
          const stepClass = result
            ? "done"
            : processState === "processing" && activeIndex === index
              ? "active pulse"
              : processState === "processing" && activeIndex > index
                ? "done"
                : "";
          return (
            <Fragment key={`${label}-${index}`}>
              <ChevronRight size={13} />
              <div className={`pipeline-step ${stepClass}`}>
                <b>{stepClass === "done" ? <Check size={10} /> : firstStepNumber + index + 1}</b> {label}
              </div>
            </Fragment>
          );
        })}
        <ChevronRight size={13} />
        <div className={`pipeline-step ${result ? "done" : ""}`}><b>{result ? <Check size={10} /> : firstStepNumber + pipelineShape.length + 1}</b> JSON validation</div>
      </footer>
    </>
  );
}
