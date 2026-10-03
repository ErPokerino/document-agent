"use client";

import {
  AlertCircle,
  BrainCircuit,
  Cloud,
  Database,
  Download,
  FileDown,
  GraduationCap,
  HardDrive,
  LoaderCircle,
  Play,
  Square,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, apiUrls } from "../lib/api";
import { formatBytes, percent } from "../lib/format";
import { stepLabel } from "../lib/pipeline-editor";
import { uploadsOnlyScans } from "../lib/pipeline-steps";
import {
  dateFields,
  emptyTrainingForm,
  jobProgress,
  predictableFields,
  provenance,
  readingKinds,
  trainingDataFlow,
  trainingProblems,
  trainingRequest,
  type TrainingForm,
} from "../lib/training";
import { InfoHint } from "./info-hint";
import type {
  ArtifactSummary,
  Dataset,
  EntityDefinition,
  FineTuningExportRequest,
  KnnParameters,
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
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [exportForm, setExportForm] = useState<FineTuningExportRequest>({ name: "", datasets: [], pipeline: "", format: "vertex_gemini" });
  const importInput = useRef<HTMLInputElement>(null);

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
        const [nextDatasets, nextPipelines, nextProviders, nextArtifacts, nextJobs, nextCache] = await Promise.all([
          api.datasets(), api.pipelines(), api.trainingProviders(), api.artifacts(), api.trainingJobs(), api.readingCache(),
        ]);
        if (!active) return;
        setDatasets(nextDatasets);
        setPipelines(nextPipelines);
        setProviders(nextProviders);
        setArtifacts(nextArtifacts);
        setJobs(nextJobs);
        setCache(nextCache);
        // The first pipeline that reads text: one that does not cannot train.
        const reading = nextPipelines.find((pipeline) => readingKinds(pipeline.steps.map((step) => step.kind)).length) ?? nextPipelines[0];
        setForm((current) => current.pipeline ? current : { ...current, pipeline: reading?.name ?? "" });
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

  const problems = trainingProblems(form);
  const chosenPipeline = pipelines.find((pipeline) => pipeline.name === form.pipeline);
  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  const setParameters = (change: Partial<KnnParameters>) => setForm({ ...form, parameters: { ...form.parameters, ...change } });

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

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><GraduationCap size={18} /></span>
          <div>
            <h3>Train a nearest-neighbour model<InfoHint text="Every labelled document is turned into a TF-IDF vector of its text. A new document takes the labels of the most similar one, and the similarity is a number to set a threshold on. Suited to categorical fields that repeat with the sender: document type, cost centre, supplier id." /></h3>
            <p>Learns from the text of labelled documents, read by the reading steps of a pipeline. Runs on this machine.</p>
          </div>
        </div>

        <div className="training-form">
          <label className="flow-field">
            <span>Name</span>
            <input aria-label="Model name" value={form.name} placeholder="Supplier ids, 2025" onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>

          <fieldset className="flow-field training-choices">
            <legend>Learn from<InfoHint text="Keep the datasets a Lab run will score apart from these: the Lab refuses to score a model on documents it learned from." /></legend>
            {datasets.length === 0 && <p className="field-help">No dataset yet. Create one in Datasets.</p>}
            {datasets.map((dataset) => (
              <label key={dataset.name}>
                <input type="checkbox" checked={form.datasets.includes(dataset.name)} onChange={() => setForm({ ...form, datasets: toggle(form.datasets, dataset.name) })} />
                <span>{dataset.name}</span>
                <small>{dataset.labelled_count} labelled</small>
              </label>
            ))}
          </fieldset>

          <fieldset className="flow-field training-choices">
            <legend>Fields to predict<InfoHint text="Categories first: a neighbour's label is the right answer for a class that repeats with the sender, not for an amount or a number unique to each document." /></legend>
            {predictableFields(entities).map((entity) => (
              <label key={entity.name}>
                <input type="checkbox" checked={form.entities.includes(entity.name)} onChange={() => setForm({ ...form, entities: toggle(form.entities, entity.name) })} />
                <span>{entity.name}</span>
                <small>{entity.format}{entity.format === "category" ? (entity.categories?.length ? " · closed" : " · open") : ""}</small>
              </label>
            ))}
          </fieldset>

          <label className="flow-field">
            <span>Read text as the pipeline<InfoHint text="The reading steps of this pipeline — before its first step that fills fields — produce the text. A pipeline that uses the model should read text the same way; Pipelines warns when it does not. Stored Document AI readings are reused, so a document already read by OCR is not paid for again." /></span>
            <select aria-label="Pipeline that reads the text" value={form.pipeline} onChange={(event) => setForm({ ...form, pipeline: event.target.value })}>
              {pipelines.map((pipeline) => (
                <option key={pipeline.name} value={pipeline.name}>
                  {pipeline.name} · {pipeline.steps.map((step) => stepLabel(step.kind)).join(" → ")}
                </option>
              ))}
            </select>
          </label>

          {chosenPipeline && (
            <p className="field-help training-flow">
              Reads with {readingKinds(chosenPipeline.steps.map((step) => step.kind)).map(stepLabel).join(" → ") || "nothing"}. {trainingDataFlow(chosenPipeline.steps.map((step) => step.kind), uploadsOnlyScans(chosenPipeline.steps.filter((step) => readingKinds([step.kind]).length)))}
            </p>
          )}

          <div className="training-split">
            <label className="flow-field">
              <span>Temporal split<InfoHint text="Learn only from documents dated before this day by their own label; the later ones can then form the dataset the Lab scores the model on, as new documents would arrive." /></span>
              <select aria-label="Date field for the split" value={form.cutoffEntity} onChange={(event) => setForm({ ...form, cutoffEntity: event.target.value })}>
                <option value="">No split: every labelled document</option>
                {dateFields(entities).map((entity) => <option key={entity.name} value={entity.name}>{entity.name}</option>)}
              </select>
            </label>
            <label className="flow-field">
              <span>Dated before</span>
              <input type="date" aria-label="Learn from documents dated before" disabled={!form.cutoffEntity} value={form.cutoffBefore} onChange={(event) => setForm({ ...form, cutoffBefore: event.target.value })} />
            </label>
          </div>

          <details className="training-parameters">
            <summary>Parameters</summary>
            <div className="training-parameter-grid">
              <label className="flow-field">
                <span>Features<InfoHint text="Character n-grams inside word boundaries tolerate OCR noise: a word misread by one letter keeps most of its n-grams. Whole words are sharper on clean text." /></span>
                <select aria-label="Features" value={form.parameters.analyzer} onChange={(event) => setParameters({ analyzer: event.target.value as KnnParameters["analyzer"] })}>
                  <option value="char_wb">Character n-grams</option>
                  <option value="word">Words</option>
                </select>
              </label>
              <label className="flow-field"><span>Shortest n-gram</span>
                <input type="number" aria-label="Shortest n-gram" min={1} max={8} value={form.parameters.ngram_min} onChange={(event) => setParameters({ ngram_min: Number(event.target.value) })} />
              </label>
              <label className="flow-field"><span>Longest n-gram</span>
                <input type="number" aria-label="Longest n-gram" min={1} max={8} value={form.parameters.ngram_max} onChange={(event) => setParameters({ ngram_max: Number(event.target.value) })} />
              </label>
              <label className="flow-field"><span>Neighbours (k)<InfoHint text="How many of the nearest labelled documents vote. 1 takes the single nearest; more lets a majority overrule one odd neighbour." /></span>
                <input type="number" aria-label="Neighbours" min={1} max={25} value={form.parameters.k} onChange={(event) => setParameters({ k: Number(event.target.value) })} />
              </label>
              <label className="flow-field"><span>Votes weighted by</span>
                <select aria-label="Vote weighting" value={form.parameters.weighting} onChange={(event) => setParameters({ weighting: event.target.value as KnnParameters["weighting"] })}>
                  <option value="distance">Similarity</option>
                  <option value="uniform">One vote each</option>
                </select>
              </label>
              <label className="flow-field"><span>Ignore terms in more than<InfoHint text="A term found in more than this share of the documents is left out: it says nothing about which document this is." /></span>
                <input type="number" aria-label="Maximum document frequency" min={0.05} max={1} step={0.05} value={form.parameters.max_df} onChange={(event) => setParameters({ max_df: Number(event.target.value) })} />
              </label>
              <label className="flow-field"><span>Ignore terms in fewer than</span>
                <input type="number" aria-label="Minimum document count" min={1} max={100} value={form.parameters.min_df} onChange={(event) => setParameters({ min_df: Number(event.target.value) })} />
              </label>
              <label className="flow-field"><span>Characters compared<InfoHint text="How much of each document's text is compared, from its start, where the sender and document type are printed." /></span>
                <input type="number" aria-label="Characters compared" min={200} max={500000} step={1000} value={form.parameters.max_characters} onChange={(event) => setParameters({ max_characters: Number(event.target.value) })} />
              </label>
              <label className="flow-field training-checkbox">
                <input type="checkbox" checked={form.parameters.sublinear_tf} onChange={(event) => setParameters({ sublinear_tf: event.target.checked })} />
                <span>Dampen repeated terms (log term frequency)</span>
              </label>
            </div>
          </details>
        </div>

        {problems.length > 0 && <p className="field-help">{problems.join(" ")}</p>}
        <div className="run-controls training-actions">
          {running ? (
            <>
              <span className="run-progress"><LoaderCircle className="spin" size={15} /> {running.name} · {jobProgress(running)}</span>
              <button className="secondary-button" onClick={() => guard(async () => { await api.cancelTrainingJob(running.id); await refresh(); })}>
                <Square size={14} /> Cancel
              </button>
            </>
          ) : (
            <button className="primary-button" disabled={busy || problems.length > 0} onClick={() => guard(async () => { await api.trainKnn(trainingRequest(form)); await refresh(); })}>
              <Play size={14} /> Train
            </button>
          )}
        </div>

        {jobs.filter((job) => job.status !== "running" && job.kind !== "fine_tuning_export").slice(0, 3).map((job) => (
          <div className={`training-job ${job.status}`} key={job.id}>
            <strong>{job.name}</strong> <span>{jobProgress(job)}</span>
            {job.skipped.length > 0 && (
              <details><summary>{job.skipped.length} not read</summary><ul>{job.skipped.map((line) => <li key={line}>{line}</li>)}</ul></details>
            )}
          </div>
        ))}
      </div>

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Database size={18} /></span>
          <div>
            <h3>Trained models<InfoHint text="A model is never changed once stored. Its id is a hash of its files and how it was trained, so a pipeline that names it and a Lab run that used it point at exactly this model." /></h3>
            <p>Use one in a pipeline with the <strong>Trained model</strong> step. Export carries a model to another machine.</p>
          </div>
          <button className="secondary-button small" disabled={busy} onClick={() => importInput.current?.click()}><Upload size={13} /> Import</button>
          <input
            ref={importInput}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void guard(async () => { await api.importArtifact(file); await refresh(); });
            }}
          />
        </div>
        {artifacts.length === 0 && <p className="field-help">No model yet. Train one above, or import an exported one.</p>}
        <div className="artifact-list">
          {artifacts.map((artifact) => (
            <div className="artifact-card" key={artifact.id}>
              <div className="artifact-head">
                <strong>{artifact.name}</strong>
                <code title={artifact.id}>{artifact.id.slice(0, 8)}</code>
                <span className="pages-tag">{artifact.kind === "knn_tfidf" ? "Nearest neighbour · TF-IDF" : artifact.kind}</span>
                {artifact.imported && <span className="pages-tag">Imported</span>}
                <span className="artifact-actions">
                  <a className="secondary-button small" href={apiUrls.artifactZip(artifact.id)} download><Download size={13} /> Export</a>
                  {confirmingDelete === artifact.id ? (
                    <>
                      <button className="secondary-button small" onClick={() => setConfirmingDelete(null)}>Keep</button>
                      <button className="secondary-button small danger" onClick={() => guard(async () => { setConfirmingDelete(null); await api.deleteArtifact(artifact.id); await refresh(); })}>Delete</button>
                    </>
                  ) : (
                    <button className="icon-button" aria-label={`Delete ${artifact.name}`} disabled={artifact.used_by.length > 0} title={artifact.used_by.length ? `Used by ${artifact.used_by.join(", ")}` : "Delete this model"} onClick={() => setConfirmingDelete(artifact.id)}><Trash2 size={15} /></button>
                  )}
                </span>
              </div>
              <p className="field-help">{provenance(artifact)} · {formatBytes(artifact.size_bytes)}</p>
              <table className="classification-table">
                <thead>
                  <tr>
                    <th>Field</th><th>Documents</th><th>Classes</th>
                    <th>Accuracy<InfoHint text="Leave-one-out: each training document predicted from all the others, copies of the same file left out together. A measure of documents like these, not a Lab result." /></th>
                    <th>Macro F1</th>
                  </tr>
                </thead>
                <tbody>
                  {artifact.entities.map((name) => {
                    const measured = artifact.validation[name];
                    return (
                      <tr key={name}>
                        <td>{name}</td>
                        <td>{measured?.documents ?? "—"}</td>
                        <td>{measured?.classes ?? "—"}</td>
                        <td>{percent(measured?.accuracy)}</td>
                        <td>{measured?.macro_f1 == null ? "—" : measured.macro_f1.toFixed(2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {artifact.used_by.length > 0 && (
                <p className="field-help">Used by <button type="button" className="link-button" onClick={onPipelines}>{artifact.used_by.join(", ")}</button></p>
              )}
            </div>
          ))}
        </div>
      </div>

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
