"use client";

import { Grid3x3, Play } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { planGrid, planSummary, type ModelPick } from "../../lib/experiments";
import { stepLabel } from "../../lib/pipeline-editor";
import { usesModel } from "../../lib/pipeline-steps";
import { InfoHint } from "../components/info-hint";
import type { Dataset, Experiment, ModelInfo, SavedPipeline } from "../../lib/types";

type Props = {
  datasets: Dataset[];
  dataset: string | null;
  onDataset: (name: string | null) => void;
  busy: boolean;
  running: boolean;
  onStarted: (experiment: Experiment) => void;
  onError: (message: string) => void;
};

/**
 * Choose pipelines and models; see the grid that will run before it runs.
 *
 * Every cell is an ordinary Lab run. What the person needs to see before
 * starting is how many runs that is, which cells will not run and why, and
 * what happens to the model in memory.
 */
export function ExperimentBuilder({ datasets, dataset, onDataset, busy, running, onStarted, onError }: Props) {
  const [pipelines, setPipelines] = useState<SavedPipeline[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [pickedPipelines, setPickedPipelines] = useState<string[]>([]);
  const [pickedModels, setPickedModels] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [reuseReadings, setReuseReadings] = useState(false);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([api.pipelines(), api.models().catch(() => [] as ModelInfo[])])
      .then(([nextPipelines, nextModels]) => {
        if (!active) return;
        setPipelines(nextPipelines.filter((pipeline) => pipeline.problems.length === 0));
        setModels(nextModels);
      })
      .catch((cause) => onError(cause instanceof Error ? cause.message : String(cause)));
    return () => { active = false; };
  }, [onError]);

  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((item) => item !== value) : [...list, value]);
  const modelKey = (model: ModelInfo) => `${model.provider}\u0000${model.id}`;
  const chosenPipelines = pipelines.filter((pipeline) => pickedPipelines.includes(pipeline.name));
  const chosenModels: ModelPick[] = models.filter((model) => pickedModels.includes(modelKey(model)));
  const cells = planGrid(chosenPipelines, chosenModels);
  const labelled = datasets.find((entry) => entry.name === dataset)?.labelled_count ?? 0;
  const needsModel = chosenPipelines.some((pipeline) => usesModel(pipeline.steps.map((step) => step.kind)));
  const columns = [...chosenModels.map((model) => model.id), ...(cells.some((cell) => cell.state === "once") ? [null] : [])];
  const problem = !dataset
    ? "Choose a dataset."
    : !chosenPipelines.length
      ? "Choose at least one pipeline."
      : needsModel && !chosenModels.length
        ? "A chosen pipeline calls a model: choose at least one."
        : !cells.some((cell) => cell.state !== "skipped")
          ? "Every cell is skipped."
          : null;
  const local = chosenModels.filter((model) => model.provider === "lm_studio");

  async function start() {
    setStarting(true);
    try {
      onStarted(await api.startExperiment({
        name: name.trim(),
        dataset: dataset!,
        pipelines: pickedPipelines,
        models: chosenModels.map((model) => ({ provider: model.provider, model: model.id })),
        reuse_readings: reuseReadings,
      }));
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="experiment-builder">
      <ol className="experiment-steps">
        <li>
          <h4><span>1</span> Dataset</h4>
          <select aria-label="Experiment dataset" value={dataset ?? ""} onChange={(event) => onDataset(event.target.value || null)}>
            <option value="">Choose a dataset…</option>
            {datasets.map((entry) => <option key={entry.name} value={entry.name} disabled={entry.labelled_count === 0}>{entry.name} ({entry.labelled_count} labelled)</option>)}
          </select>
        </li>
        <li>
          <h4><span>2</span> Pipelines <small>rows</small></h4>
          <div className="experiment-choices">
            {pipelines.map((pipeline) => {
              const calls = usesModel(pipeline.steps.map((step) => step.kind));
              return (
                <label key={pipeline.name} title={pipeline.steps.map((step) => stepLabel(step.kind)).join(" → ")}>
                  <input type="checkbox" checked={pickedPipelines.includes(pipeline.name)} onChange={() => setPickedPipelines(toggle(pickedPipelines, pipeline.name))} />
                  <span>{pipeline.name}</span>
                  <small>{calls ? "calls a model" : "no model"}</small>
                </label>
              );
            })}
          </div>
        </li>
        <li>
          <h4>
            <span>3</span> Models <small>columns</small>
            <InfoHint text="Each pipeline that calls a model runs once per model chosen here. A pipeline that calls no model runs once. Local models are loaded one after another, each once; the model selected in LLM is not changed, but another one may be in memory when the experiment ends." />
          </h4>
          <div className="experiment-choices">
            {models.length === 0 && <p className="field-help">No model is reachable. Local models come from LM Studio; hosted ones need a key in LLM.</p>}
            {models.map((model) => (
              <label key={modelKey(model)}>
                <input type="checkbox" checked={pickedModels.includes(modelKey(model))} onChange={() => setPickedModels(toggle(pickedModels, modelKey(model)))} />
                <span>{model.name}</span>
                <small>{model.provider === "gemini" ? "hosted" : "local"}{model.vision === false && model.capabilities_known !== false ? " · text only" : ""}</small>
              </label>
            ))}
          </div>
        </li>
      </ol>

      {chosenPipelines.length > 0 && (
        <div className="experiment-preview">
          <h4><Grid3x3 size={14} /> The grid that will run</h4>
          <div className="confusion-scroll">
            <table className="experiment-grid preview">
              <thead>
                <tr>
                  <th aria-label="Pipeline" />
                  {columns.map((column) => <th key={column ?? "none"}>{column === null ? "No model called" : models.find((model) => model.id === column)?.name ?? column}</th>)}
                </tr>
              </thead>
              <tbody>
                {chosenPipelines.map((pipeline) => (
                  <tr key={pipeline.name}>
                    <th>{pipeline.name}</th>
                    {columns.map((column) => {
                      const cell = cells.find((entry) => entry.pipeline === pipeline.name && entry.model === column);
                      return (
                        <td key={column ?? "none"} className={cell ? `planned ${cell.state}` : "empty"} title={cell?.reason}>
                          {!cell ? "" : cell.state === "skipped" ? "Skipped" : cell.state === "once" ? "Runs once" : "Runs"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="field-help">{planSummary(cells, labelled)}.{local.length > 1 ? ` ${local.length} local models are loaded in turn.` : ""}</p>
        </div>
      )}

      <div className="experiment-start">
        <label className="flow-field">
          <span>Name</span>
          <input aria-label="Experiment name" value={name} placeholder="Optional" onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="run-option">
          <input type="checkbox" checked={reuseReadings} onChange={(event) => setReuseReadings(event.target.checked)} />
          <span>Reuse stored Document AI readings</span>
          <InfoHint text="Every cell reads stored OCR and Layout Parser readings back instead of sending the pages again. Accuracy is compared as usual; time and cost are then not what the pipelines cost." />
        </label>
        <button className="primary-button" disabled={busy || running || starting || problem !== null} onClick={() => void start()}>
          <Play size={14} /> Start experiment
        </button>
      </div>
      {problem && <p className="field-help">{problem}</p>}
    </div>
  );
}
