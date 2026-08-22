"use client";

import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  CheckCircle2,
  Copy,
  LoaderCircle,
  Plus,
  Save,
  Trash2,
  Workflow,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import {
  addStep,
  emptyRule,
  moveStep,
  removeStep,
  rulesOf,
  setStepConfig,
  summarizeStep,
  type RegexRule,
} from "../lib/pipeline-editor";
import type {
  AppSettings,
  EntityDefinition,
  PipelineDefinition,
  PipelineStep,
  SavedPipeline,
  StepCatalogueEntry,
  StepKind,
} from "../lib/types";

type Props = {
  draftSettings: AppSettings;
  entities: EntityDefinition[];
  onUse: (name: string) => Promise<void>;
};

const whenLabels: Record<RegexRule["when"], string> = {
  always: "Always",
  if_empty: "Only if the model returned nothing",
  if_low_confidence: "Only if the model was unsure",
};

const sourceLabels: Record<RegexRule["source"], string> = {
  value: "What the model returned",
  text: "The document text",
};

/** Compose the steps a document goes through, and save that as a pipeline. */
export function Pipelines({ draftSettings, entities, onUse }: Props) {
  const [pipelines, setPipelines] = useState<SavedPipeline[]>([]);
  const [catalogue, setCatalogue] = useState<StepCatalogueEntry[]>([]);
  const [draft, setDraft] = useState<PipelineDefinition | null>(null);
  const [openedAs, setOpenedAs] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);

  const inUse = draftSettings.pipeline;
  const entityNames = entities.map((entity) => entity.name);

  async function refresh() {
    setPipelines(await api.pipelines());
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [saved, steps] = await Promise.all([api.pipelines(), api.pipelineSteps()]);
        if (!active) return;
        setPipelines(saved);
        setCatalogue(steps);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  // The backend owns the rules about what can follow what, so the warnings a
  // person sees while editing are the same ones that would refuse the save.
  useEffect(() => {
    if (!draft) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void api
        .checkPipeline(draft)
        .then((checked) => active && setProblems(checked.problems))
        .catch(() => active && setProblems([]));
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [draft]);

  function open(pipeline: SavedPipeline) {
    setDraft({ name: pipeline.name, description: pipeline.description, steps: pipeline.steps });
    setOpenedAs(pipeline.name);
    setProblems(pipeline.problems);
    setError(null);
    setState("idle");
  }

  function startNew() {
    const existing = new Set(pipelines.map((pipeline) => pipeline.name));
    let name = "New pipeline";
    let suffix = 1;
    while (existing.has(name)) name = `New pipeline ${++suffix}`;
    setDraft({
      name,
      description: "",
      steps: [
        { kind: "render_pages", config: { scale: 1.35 } },
        { kind: "llm_extract", config: {} },
      ],
    });
    setOpenedAs(null);
    setError(null);
  }

  function setSteps(steps: PipelineStep[]) {
    if (draft) setDraft({ ...draft, steps });
  }

  function setRules(index: number, rules: RegexRule[]) {
    if (draft) setSteps(setStepConfig(draft.steps, index, { rules }));
  }

  async function save() {
    if (!draft) return;
    setState("saving");
    setError(null);
    try {
      const saved = await api.savePipeline(draft);
      await refresh();
      setOpenedAs(saved.name);
      setProblems(saved.problems);
      setState("saved");
      window.setTimeout(() => setState("idle"), 1800);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setState("idle");
    }
  }

  async function remove(name: string) {
    setConfirmingDelete(null);
    setError(null);
    try {
      await api.deletePipeline(name);
      await refresh();
      if (openedAs === name) {
        setDraft(null);
        setOpenedAs(null);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function use(name: string) {
    setError(null);
    try {
      await onUse(name);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  const savedUnderAnotherName = draft !== null && openedAs !== null && draft.name !== openedAs;

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Workflow size={19} />
        <div>
          <h2>Pipelines</h2>
          <p>The steps a document goes through, from PDF to extracted fields.</p>
        </div>
      </div>

      {error && (
        <div className="alert error-alert" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      )}

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Workflow size={18} /></span>
          <div>
            <h3>Saved pipelines</h3>
            <p>Extraction, test runs and labelling all use the one marked in use.</p>
          </div>
          <button className="add-entity-button" onClick={startNew}><Plus size={14} /> New pipeline</button>
        </div>

        <div className="dataset-list">
          {pipelines.map((pipeline) => (
            <div className={`flow-option ${openedAs === pipeline.name ? "selected" : ""}`} key={pipeline.name}>
              {confirmingDelete === pipeline.name ? (
              <div className="row-confirm">
                <span><strong>Delete {pipeline.name}?</strong> Runs already recorded keep its name.</span>
                <button className="secondary-button small ghost" onClick={() => setConfirmingDelete(null)}>Cancel</button>
                <button className="secondary-button small danger" onClick={() => void remove(pipeline.name)}><Trash2 size={13} /> Delete</button>
              </div>
              ) : (
              <>
              <button className="flow-open" onClick={() => open(pipeline)}>
                <strong>{pipeline.name}</strong>
                <small>
                  {pipeline.steps.map((step) => summarizeStep(step)).join(" → ")}
                  {pipeline.description ? ` · ${pipeline.description}` : ""}
                </small>
              </button>
              {pipeline.problems.length > 0 && <span className="status-tag failed">Cannot run</span>}
              {inUse === pipeline.name ? (
                <span className="status-tag completed">In use</span>
              ) : (
                <button
                  className="secondary-button small"
                  disabled={pipeline.problems.length > 0}
                  onClick={() => void use(pipeline.name)}
                >
                  <Check size={13} /> Use
                </button>
              )}
              <button
                className="icon-button"
                aria-label={`Delete ${pipeline.name}`}
                disabled={inUse === pipeline.name}
                title={inUse === pipeline.name ? "Select another pipeline before deleting this one" : "Delete"}
                onClick={() => setConfirmingDelete(pipeline.name)}
              >
                <Trash2 size={15} />
              </button>
              </>
              )}
            </div>
          ))}
        </div>
      </div>

      {draft && (
        <div className="settings-card">
          <div className="settings-card-heading">
            <span className="settings-card-icon"><Workflow size={18} /></span>
            <div>
              <h3>{openedAs ?? "New pipeline"}</h3>
              <p>Each step reads what the steps before it produced.</p>
            </div>
          </div>

          <div className="flow-identity">
            <div>
              <label className="input-label" htmlFor="pipeline-name">Name</label>
              <input
                id="pipeline-name"
                className="text-input"
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </div>
            <div>
              <label className="input-label" htmlFor="pipeline-description">Description</label>
              <input
                id="pipeline-description"
                className="text-input"
                placeholder="What this pipeline is for"
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              />
            </div>
          </div>

          {savedUnderAnotherName && (
            <p className="field-help"><Copy size={12} /> Saving now creates a copy called <strong>{draft.name}</strong>; <strong>{openedAs}</strong> stays as it is.</p>
          )}

          <div className="flow-steps">
            {draft.steps.map((step, index) => {
              const contract = catalogue.find((entry) => entry.kind === step.kind);
              const rules = rulesOf(step);
              return (
                <div className="flow-step" key={`${step.kind}-${index}`}>
                  <div className="flow-step-head">
                    <span className="flow-step-index">{index + 1}</span>
                    <div>
                      <strong>{contract?.label ?? step.kind}</strong>
                      <small>{contract?.description ?? ""}</small>
                    </div>
                    <button className="icon-button" aria-label="Move up" disabled={index === 0} onClick={() => setSteps(moveStep(draft.steps, index, -1))}><ArrowUp size={14} /></button>
                    <button className="icon-button" aria-label="Move down" disabled={index === draft.steps.length - 1} onClick={() => setSteps(moveStep(draft.steps, index, 1))}><ArrowDown size={14} /></button>
                    <button className="icon-button" aria-label="Remove step" onClick={() => setSteps(removeStep(draft.steps, index))}><Trash2 size={14} /></button>
                  </div>

                  {step.kind === "render_pages" && (
                    <div className="flow-step-body">
                      <label className="flow-field">
                        <span>Zoom</span>
                        <input
                          type="number"
                          min={0.5}
                          max={4}
                          step={0.05}
                          value={Number((step.config as { scale?: number }).scale ?? 1.35)}
                          onChange={(event) => setSteps(setStepConfig(draft.steps, index, { scale: Number(event.target.value) }))}
                        />
                      </label>
                      <p className="field-help">Higher zoom reads small print better and costs more memory and time. How many pages are rendered comes from the page limit in Models.</p>
                    </div>
                  )}

                  {step.kind === "llm_extract" && (
                    <div className="flow-step-body">
                      <p className="field-help">Uses the model selected in Models and the prompts written in Prompts. One call per document.</p>
                    </div>
                  )}

                  {step.kind === "regex_refine" && (
                    <div className="flow-step-body">
                      <div className="flow-rules">
                        {rules.map((rule, ruleIndex) => {
                          const update = (change: Partial<RegexRule>) =>
                            setRules(index, rules.map((existing, position) => (position === ruleIndex ? { ...existing, ...change } : existing)));
                          return (
                            <div className="flow-rule" key={ruleIndex}>
                              <label><span>Field</span>
                                <select value={rule.entity} onChange={(event) => update({ entity: event.target.value })}>
                                  {entityNames.map((name) => <option key={name} value={name}>{name}</option>)}
                                </select>
                              </label>
                              <label><span>Read from</span>
                                <select value={rule.source} onChange={(event) => update({ source: event.target.value as RegexRule["source"] })}>
                                  {Object.entries(sourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                              </label>
                              <label><span>When</span>
                                <select value={rule.when} onChange={(event) => update({ when: event.target.value as RegexRule["when"] })}>
                                  {Object.entries(whenLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                                </select>
                              </label>
                              <label><span>Pattern</span>
                                <input value={rule.pattern} placeholder="\s*-\s*" onChange={(event) => update({ pattern: event.target.value })} />
                              </label>
                              <label><span>Capture group</span>
                                <input
                                  type="number"
                                  min={0}
                                  placeholder="none"
                                  value={rule.group ?? ""}
                                  onChange={(event) => update({ group: event.target.value === "" ? null : Number(event.target.value) })}
                                />
                              </label>
                              <label><span>Replace with</span>
                                <input
                                  value={rule.replacement}
                                  disabled={rule.group !== null}
                                  onChange={(event) => update({ replacement: event.target.value })}
                                />
                              </label>
                              <button className="icon-button" aria-label="Remove rule" onClick={() => setRules(index, rules.filter((_, position) => position !== ruleIndex))}><Trash2 size={14} /></button>
                            </div>
                          );
                        })}
                      </div>
                      <div className="flow-rule-actions">
                        <button className="secondary-button small" disabled={entityNames.length === 0} onClick={() => setRules(index, [...rules, emptyRule(entityNames[0] ?? "")])}>
                          <Plus size={13} /> Add rule
                        </button>
                        <p className="field-help">
                          A capture group takes that part of the match; leave it empty to substitute across the match instead.
                          The result is checked against the field format, exactly like a model answer.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="flow-add-step">
            {catalogue.map((entry) => (
              <button className="secondary-button small" key={entry.kind} onClick={() => setSteps(addStep(draft.steps, entry.kind as StepKind))}>
                <Plus size={13} /> {entry.label}
              </button>
            ))}
          </div>

          {problems.length > 0 && (
            <div className="alert error-alert" role="status">
              <AlertCircle size={17} />
              <span>{problems.join(" ")}</span>
            </div>
          )}

          <div className="settings-actions">
            <p><Workflow size={14} /> {inUse === draft.name ? "This is the pipeline in use." : "Save it, then press Use to run documents through it."}</p>
            <button className="primary-button save-button" disabled={state === "saving" || problems.length > 0 || !draft.name.trim()} onClick={() => void save()}>
              {state === "saving" ? <LoaderCircle className="spin" size={15} /> : state === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
              {state === "saving" ? "Saving…" : state === "saved" ? "Saved" : savedUnderAnotherName ? "Save as copy" : "Save pipeline"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
