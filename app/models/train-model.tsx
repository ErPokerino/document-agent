"use client";

import { GraduationCap, LoaderCircle, Play, Square } from "lucide-react";

import { stepLabel } from "../../lib/pipeline-editor";
import { uploadsOnlyScans } from "../../lib/pipeline-steps";
import {
  FAMILY_LABELS,
  STATUS_LABELS,
  dateFields,
  groupAlgorithms,
  jobProgress,
  predictableFields,
  readingKinds,
  trainingDataFlow,
  trainingProblems,
  withAlgorithm,
  type ParameterValue,
  type TrainingForm,
} from "../../lib/training";
import { InfoHint } from "../components/info-hint";
import type { AlgorithmInfo, Dataset, EntityDefinition, ParameterSpec, SavedPipeline, TextFeatures, TrainingJobModel } from "../../lib/types";

type Props = {
  algorithms: AlgorithmInfo[];
  entities: EntityDefinition[];
  datasets: Dataset[];
  pipelines: SavedPipeline[];
  form: TrainingForm;
  setForm: (form: TrainingForm) => void;
  running: TrainingJobModel | null;
  recent: TrainingJobModel[];
  busy: boolean;
  onTrain: () => void;
  onCancel: (job: TrainingJobModel) => void;
};

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

/**
 * Train a model in four choices: the algorithm, the data, the features, its parameters.
 *
 * The algorithms and their parameters come from the backend, so a new one
 * appears here as a card with its settings drawn from its own description.
 */
export function TrainModelCard({ algorithms, entities, datasets, pipelines, form, setForm, running, recent, busy, onTrain, onCancel }: Props) {
  const chosen = algorithms.find((algorithm) => algorithm.id === form.algorithm);
  const problems = trainingProblems(form, chosen);
  const pipeline = pipelines.find((entry) => entry.name === form.pipeline);
  const kinds = pipeline?.steps.map((step) => step.kind) ?? [];
  const setText = (change: Partial<TextFeatures>) => setForm({ ...form, text: { ...form.text, ...change } });
  const inputCandidates = entities.filter((entity) => !form.entities.includes(entity.name));

  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon"><GraduationCap size={18} /></span>
        <div>
          <h3>Train a model</h3>
          <p>Learns from labelled datasets, on this machine, and is checked by cross-validation before it is kept.</p>
        </div>
      </div>

      <ol className="training-steps">
        <li>
          <h4><span>1</span> Algorithm</h4>
          <div className="algorithm-families">
            {groupAlgorithms(algorithms).map((group) => (
              <div className="algorithm-family" key={group.family}>
                <h5>{FAMILY_LABELS[group.family].title}<small>{FAMILY_LABELS[group.family].blurb}</small></h5>
                <div className="algorithm-cards">
                  {group.algorithms.map((algorithm) => (
                    <button
                      type="button"
                      key={algorithm.id}
                      className={`algorithm-card ${algorithm.id === form.algorithm ? "selected" : ""} ${algorithm.status}`}
                      aria-pressed={algorithm.id === form.algorithm}
                      onClick={() => setForm(withAlgorithm(form, algorithm))}
                    >
                      <strong>{algorithm.label}</strong>
                      <span className={`algorithm-status ${algorithm.status}`}>{STATUS_LABELS[algorithm.status]}</span>
                      <small>{algorithm.runs === "remote" ? "Hosted service" : algorithm.takes_fields ? "Text and fields" : "Text"}</small>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          {chosen && (
            <div className={`algorithm-detail ${chosen.status}`}>
              <p>{chosen.description}</p>
              {chosen.status === "not_installed" && <p><strong>Not installed on this machine.</strong> <code>{chosen.install}</code></p>}
              {chosen.status === "not_connected" && <p><strong>Not connected.</strong> DocuFlow does not reach this service yet, so it cannot train or predict here.</p>}
            </div>
          )}
        </li>

        <li>
          <h4><span>2</span> Data</h4>
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
              <legend>Fields to predict<InfoHint text="One model per field, over the same features. Categories first: a class that repeats with the sender is what these models learn well; an amount or a number unique to each document is not." /></legend>
              {predictableFields(entities).map((entity) => (
                <label key={entity.name}>
                  <input type="checkbox" checked={form.entities.includes(entity.name)} onChange={() => setForm({ ...form, entities: toggle(form.entities, entity.name), inputFields: form.inputFields.filter((name) => name !== entity.name) })} />
                  <span>{entity.name}</span>
                  <small>{entity.format}{entity.format === "category" ? (entity.categories?.length ? " · closed" : " · open") : ""}</small>
                </label>
              ))}
            </fieldset>
            <label className="flow-field">
              <span>Read text as the pipeline<InfoHint text="The reading steps of this pipeline — before its first step that fills fields — produce the text. A pipeline that uses the model should read text the same way; Pipelines warns when it does not." /></span>
              <select aria-label="Pipeline that reads the text" value={form.pipeline} onChange={(event) => setForm({ ...form, pipeline: event.target.value })}>
                {pipelines.map((entry) => (
                  <option key={entry.name} value={entry.name}>{entry.name} · {entry.steps.map((step) => stepLabel(step.kind)).join(" → ")}</option>
                ))}
              </select>
            </label>
            {pipeline && (
              <p className="field-help training-flow">
                Reads with {readingKinds(kinds).map(stepLabel).join(" → ") || "nothing"}. {trainingDataFlow(kinds, uploadsOnlyScans(pipeline.steps.filter((step) => readingKinds([step.kind]).length)))}
              </p>
            )}
            <div className="training-split">
              <label className="flow-field">
                <span>Temporal split<InfoHint text="Learn only from documents dated before this day by their own label; the later ones can form the dataset the Lab scores the model on, as new documents would arrive." /></span>
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
          </div>
        </li>

        <li>
          <h4><span>3</span> Features</h4>
          <div className="training-parameter-grid">
            <label className="flow-field">
              <span>Text as<InfoHint text="Character n-grams inside word boundaries tolerate OCR noise: a word misread by one letter keeps most of its n-grams. Whole words are sharper on clean text." /></span>
              <select aria-label="Text features" value={form.text.analyzer} onChange={(event) => setText({ analyzer: event.target.value as TextFeatures["analyzer"] })}>
                <option value="char_wb">Character n-grams</option>
                <option value="word">Words</option>
              </select>
            </label>
            <label className="flow-field"><span>Shortest n-gram</span>
              <input type="number" aria-label="Shortest n-gram" min={1} max={8} value={form.text.ngram_min} onChange={(event) => setText({ ngram_min: Number(event.target.value) })} />
            </label>
            <label className="flow-field"><span>Longest n-gram</span>
              <input type="number" aria-label="Longest n-gram" min={1} max={8} value={form.text.ngram_max} onChange={(event) => setText({ ngram_max: Number(event.target.value) })} />
            </label>
            <label className="flow-field"><span>Ignore terms in more than<InfoHint text="A term found in more than this share of the documents is left out: it says nothing about which document this is." /></span>
              <input type="number" aria-label="Maximum document frequency" min={0.05} max={1} step={0.05} value={form.text.max_df} onChange={(event) => setText({ max_df: Number(event.target.value) })} />
            </label>
            <label className="flow-field"><span>Ignore terms in fewer than</span>
              <input type="number" aria-label="Minimum document count" min={1} max={100} value={form.text.min_df} onChange={(event) => setText({ min_df: Number(event.target.value) })} />
            </label>
            <label className="flow-field"><span>Characters compared<InfoHint text="How much of each document's text is read, from its start, where the sender and document type are printed." /></span>
              <input type="number" aria-label="Characters compared" min={200} max={500000} step={1000} value={form.text.max_characters} onChange={(event) => setText({ max_characters: Number(event.target.value) })} />
            </label>
            {chosen?.id !== "knn_tfidf" && (
              <label className="flow-field"><span>Reduce to dimensions<InfoHint text="Truncated SVD of the TF-IDF to this many dense dimensions. Trees and tabular foundation models work on a few hundred dense columns; linear models read the sparse TF-IDF well. Empty keeps it sparse." /></span>
                <input type="number" aria-label="Reduce to dimensions" min={2} max={2000} placeholder="Keep sparse" value={form.text.reduce_to ?? ""} onChange={(event) => setText({ reduce_to: event.target.value === "" ? null : Number(event.target.value) })} />
              </label>
            )}
            <label className="flow-field training-checkbox">
              <input type="checkbox" checked={form.text.sublinear_tf} onChange={(event) => setText({ sublinear_tf: event.target.checked })} />
              <span>Dampen repeated terms</span>
            </label>
          </div>
          {chosen?.takes_fields && (
            <fieldset className="flow-field training-choices input-fields">
              <legend>Also read these fields<InfoHint text="Extracted fields as features beside the text: an amount as a number, a date as year, month and day, anything else as one column per value seen in training. Learned from the labels; at run time read from what earlier steps of the pipeline extracted, which may be less clean than the labels were." /></legend>
              {inputCandidates.map((entity) => (
                <label key={entity.name}>
                  <input type="checkbox" checked={form.inputFields.includes(entity.name)} onChange={() => setForm({ ...form, inputFields: toggle(form.inputFields, entity.name) })} />
                  <span>{entity.name}</span>
                  <small>{entity.format}</small>
                </label>
              ))}
            </fieldset>
          )}
        </li>

        <li>
          <h4><span>4</span> Parameters {chosen && <small>{chosen.label}</small>}</h4>
          {!chosen ? (
            <p className="field-help">Choose an algorithm to see its parameters.</p>
          ) : chosen.parameters.length === 0 ? (
            <p className="field-help">{chosen.label} has no parameters to set here.</p>
          ) : (
            <div className="training-parameter-grid">
              {chosen.parameters.map((spec) => (
                <ParameterInput key={spec.name} spec={spec} value={form.parameters[spec.name]} onChange={(value) => setForm({ ...form, parameters: { ...form.parameters, [spec.name]: value } })} />
              ))}
            </div>
          )}
        </li>
      </ol>

      {problems.length > 0 && <p className="field-help">{problems.join(" ")}</p>}
      <div className="run-controls training-actions">
        {running ? (
          <>
            <span className="run-progress"><LoaderCircle className="spin" size={15} /> {running.name} · {jobProgress(running)}</span>
            <button className="secondary-button" onClick={() => onCancel(running)}><Square size={14} /> Cancel</button>
          </>
        ) : (
          <button className="primary-button" disabled={busy || problems.length > 0} onClick={onTrain}>
            <Play size={14} /> Train {chosen ? chosen.label : ""}
          </button>
        )}
      </div>

      {recent.map((job) => (
        <div className={`training-job ${job.status}`} key={job.id}>
          <strong>{job.name}</strong> <span>{jobProgress(job)}</span>
          {job.skipped.length > 0 && (
            <details><summary>{job.skipped.length} not read</summary><ul>{job.skipped.map((line) => <li key={line}>{line}</li>)}</ul></details>
          )}
        </div>
      ))}
    </div>
  );
}

/** One parameter, drawn from its description: a number, a choice or a switch. */
function ParameterInput({ spec, value, onChange }: { spec: ParameterSpec; value: ParameterValue | undefined; onChange: (value: ParameterValue) => void }) {
  const label = <span>{spec.label}{spec.help && <InfoHint text={spec.help} />}</span>;
  if (spec.kind === "bool") {
    return (
      <label className="flow-field training-checkbox">
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />
        {label}
      </label>
    );
  }
  if (spec.kind === "choice") {
    return (
      <label className="flow-field">
        {label}
        <select aria-label={spec.label} value={String(value ?? spec.default)} onChange={(event) => onChange(event.target.value)}>
          {spec.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label className="flow-field">
      {label}
      <input
        type="number"
        aria-label={spec.label}
        min={spec.minimum ?? undefined}
        max={spec.maximum ?? undefined}
        step={spec.step ?? (spec.kind === "int" ? 1 : "any")}
        value={typeof value === "number" ? value : ""}
        onChange={(event) => onChange(event.target.value === "" ? "" : Number(event.target.value))}
      />
    </label>
  );
}
