"use client";

import {
  AlertCircle,
  BrainCircuit,
  Cloud,
  Download,
  FileDown,
  HardDrive,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api, apiUrls } from "../lib/api";
import { formatBytes } from "../lib/format";
import { emptyTrainingForm, jobProgress, readingKinds, trainingRequest, withAlgorithm, type TrainingForm } from "../lib/training";
import { TrainModelCard } from "./train-model";
import { TrainedModels } from "./trained-models";
import { InfoHint } from "./info-hint";
import type {
  AlgorithmInfo,
  ArtifactSummary,
  Dataset,
  EntityDefinition,
  FineTuningExportRequest,
  ReadingCacheStatus,
  SavedPipeline,
  TrainingJobModel,
  TrainingProvider,
} from "../lib/types";

type Props = {
  entities: EntityDefinition[];
  onPipelines: () => void;
};

/** What is learned from the labelled datasets, and where it is kept. */
export function Models({ entities, onPipelines }: Props) {
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([]);
  const [jobs, setJobs] = useState<TrainingJobModel[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [pipelines, setPipelines] = useState<SavedPipeline[]>([]);
  const [providers, setProviders] = useState<TrainingProvider[]>([]);
  const [cache, setCache] = useState<ReadingCacheStatus | null>(null);
  const [form, setForm] = useState<TrainingForm>(emptyTrainingForm());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [algorithms, setAlgorithms] = useState<AlgorithmInfo[]>([]);
  const [exportForm, setExportForm] = useState<FineTuningExportRequest>({ name: "", datasets: [], pipeline: "", format: "vertex_gemini" });

  const running = jobs.find((job) => job.status === "running") ?? null;

  const refresh = useCallback(async () => {
    const [nextArtifacts, nextJobs, nextCache] = await Promise.all([api.artifacts(), api.trainingJobs(), api.readingCache()]);
    setArtifacts(nextArtifacts);
    setJobs(nextJobs);
    setCache(nextCache);
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [nextDatasets, nextPipelines, nextProviders, nextArtifacts, nextJobs, nextCache, nextAlgorithms] = await Promise.all([
          api.datasets(), api.pipelines(), api.trainingProviders(), api.artifacts(), api.trainingJobs(), api.readingCache(),
          api.trainingAlgorithms(),
        ]);
        if (!active) return;
        setAlgorithms(nextAlgorithms);
        setDatasets(nextDatasets);
        setPipelines(nextPipelines);
        setProviders(nextProviders);
        setArtifacts(nextArtifacts);
        setJobs(nextJobs);
        setCache(nextCache);
        // The first pipeline that reads text: one that does not cannot train.
        const reading = nextPipelines.find((pipeline) => readingKinds(pipeline.steps.map((step) => step.kind)).length) ?? nextPipelines[0];
        // Nearest neighbour first: it learns from a handful of documents per class.
        const first = nextAlgorithms.find((algorithm) => algorithm.status === "available");
        setForm((current) => {
          const withPipeline = current.pipeline ? current : { ...current, pipeline: reading?.name ?? "" };
          return withPipeline.algorithm || !first ? withPipeline : withAlgorithm(withPipeline, first);
        });
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void load();
    return () => { active = false; };
  }, []);

  // Polled only while a job runs: training reads every document and can take
  // minutes, and the list is what says how far it got.
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => { void refresh().catch(() => undefined); }, 1000);
    return () => window.clearInterval(timer);
  }, [running, refresh]);

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

  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <BrainCircuit size={19} />
        <div>
          <h2>Models</h2>
          <p>Train models on labelled datasets, keep them, and use them as a step in a pipeline.</p>
        </div>
      </div>

      {error && (
        <div className="alert error-alert" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Close"><X size={15} /></button>
        </div>
      )}

      <TrainModelCard
        algorithms={algorithms}
        entities={entities}
        datasets={datasets}
        pipelines={pipelines}
        form={form}
        setForm={setForm}
        running={running && running.kind !== "fine_tuning_export" ? running : null}
        recent={jobs.filter((job) => job.status !== "running" && job.kind !== "fine_tuning_export").slice(0, 3)}
        busy={busy}
        onTrain={() => guard(async () => { await api.train(trainingRequest(form)); await refresh(); })}
        onCancel={(job) => guard(async () => { await api.cancelTrainingJob(job.id); await refresh(); })}
      />

      <TrainedModels
        artifacts={artifacts}
        busy={busy}
        onImport={(file) => guard(async () => { await api.importArtifact(file); await refresh(); })}
        onDelete={(artifact) => guard(async () => { await api.deleteArtifact(artifact.id); await refresh(); })}
        onPipelines={onPipelines}
      />

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><HardDrive size={18} /></span>
          <div>
            <h3>Stored Document AI readings</h3>
            <p>OCR and Layout Parser answers from pinned processor versions. Training reuses them; a Lab run reuses them only when told to.</p>
          </div>
          <button className="secondary-button small" disabled={busy || !cache?.entries} onClick={() => guard(async () => { await api.clearReadingCache(); await refresh(); })}>
            <Trash2 size={13} /> Clear
          </button>
        </div>
        <p className="field-help">{cache ? `${cache.entries} readings · ${formatBytes(cache.size_bytes)}` : "—"}</p>
      </div>

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Cloud size={18} /></span>
          <div>
            <h3>Training elsewhere</h3>
            <p>Where models will be trained once DocuFlow is connected to them. None is reachable from this app yet; the examples they train on can already be written here.</p>
          </div>
        </div>
        <div className="training-export">
          <h4>Fine-tuning examples<InfoHint text="Labelled documents written as supervised tuning examples, one JSON object per line, worded exactly as DocuFlow asks Gemini at run time: the same system instruction, page note and document text, with the labels as the answer. Text only, read by the pipeline's reading steps. A document missing a label for a field the model is asked for is left out rather than written with null." /></h4>
          <div className="training-form">
            <label className="flow-field"><span>Name</span>
              <input aria-label="Export name" value={exportForm.name} placeholder="Invoices 2025" onChange={(event) => setExportForm({ ...exportForm, name: event.target.value })} />
            </label>
            <fieldset className="flow-field training-choices">
              <legend>From</legend>
              {datasets.map((dataset) => (
                <label key={dataset.name}>
                  <input type="checkbox" checked={exportForm.datasets.includes(dataset.name)} onChange={() => setExportForm({ ...exportForm, datasets: toggle(exportForm.datasets, dataset.name) })} />
                  <span>{dataset.name}</span><small>{dataset.labelled_count} labelled</small>
                </label>
              ))}
            </fieldset>
            <label className="flow-field"><span>Text read as the pipeline</span>
              <select aria-label="Pipeline that reads the export text" value={exportForm.pipeline || form.pipeline} onChange={(event) => setExportForm({ ...exportForm, pipeline: event.target.value })}>
                {pipelines.map((pipeline) => <option key={pipeline.name} value={pipeline.name}>{pipeline.name}</option>)}
              </select>
            </label>
            <label className="flow-field"><span>Format</span>
              <select aria-label="Export format" value={exportForm.format} onChange={(event) => setExportForm({ ...exportForm, format: event.target.value as FineTuningExportRequest["format"] })}>
                <option value="vertex_gemini">Gemini on Vertex AI (contents)</option>
                <option value="openai_chat">Chat messages (system, user, assistant)</option>
              </select>
            </label>
          </div>
          <div className="run-controls training-actions">
            <button
              className="secondary-button"
              disabled={busy || !!running || !exportForm.name.trim() || !exportForm.datasets.length}
              onClick={() => guard(async () => { await api.exportFineTuning({ ...exportForm, name: exportForm.name.trim(), pipeline: exportForm.pipeline || form.pipeline }); await refresh(); })}
            >
              <FileDown size={14} /> Write examples
            </button>
          </div>
          {jobs.filter((job) => job.kind === "fine_tuning_export" && job.status !== "running").slice(0, 3).map((job) => (
            <div className={`training-job ${job.status}`} key={job.id}>
              <strong>{job.name}</strong> <span>{jobProgress(job)}</span>
              {job.output && <a className="secondary-button small" href={apiUrls.fineTuningExport(job.output)} download><Download size={13} /> {job.output}</a>}
              {job.skipped.length > 0 && (
                <details><summary>{job.skipped.length} left out</summary><ul>{job.skipped.map((line) => <li key={line}>{line}</li>)}</ul></details>
              )}
            </div>
          ))}
        </div>

        <div className="provider-list">
          {providers.map((provider) => (
            <div className="provider-card" key={provider.id}>
              <div className="artifact-head">
                <strong>{provider.name}</strong>
                <span className="pages-tag">{provider.platform}</span>
                <span className={`status-tag ${provider.status === "available" ? "completed" : "cancelled"}`}>{provider.status === "available" ? "Available" : "Not connected"}</span>
              </div>
              <p className="field-help"><strong>Trains:</strong> {provider.trains}. {provider.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
