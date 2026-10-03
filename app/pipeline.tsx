"use client";

import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  CheckCircle2,
  Copy,
  Info,
  LoaderCircle,
  Pencil,
  Plus,
  Save,
  Scissors,
  Search,
  Trash2,
  Workflow,
  X,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { OCR_ONLY_WITHOUT_PDF_TEXT, isPdfTextFallback } from "../lib/pipeline-steps";
import { ProcessorPicker } from "./processor-picker";
import { ResolveSettings } from "./resolve-settings";
import { resolutionOf, upstreamMethods } from "../lib/resolution";
import { InfoHint } from "./info-hint";
import { PipelineCanvas, STEP_ICONS } from "./pipeline-canvas";
import { flowCategory, insertFlowStep, stepProblems } from "../lib/pipeline-flow";
import "./pipeline-flow.css";
import {
  MAX_PAGES,
  MIN_PAGES,
  DEFAULT_MINIMUM_SIMILARITY,
  emptyRule,
  groupCatalogue,
  moveStep,
  pageLimitProblem,
  removeStep,
  rulesOf,
  setStepConfig,
  patchStepConfig,
  summarizeStep,
  stepLabel,
  type RegexRule,
} from "../lib/pipeline-editor";
import type {
  AppSettings,
  ArtifactSummary,
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
  onProcessors: () => void;
  onModels: () => void;
};

type TrainedModelConfig = { artifact_id?: string; entities?: string[]; minimum_similarity?: number };

/** Which trained model a step uses, which of its fields it fills, and from what similarity. */
function TrainedModelSettings({ config, artifacts, onChange, onModels }: {
  config: TrainedModelConfig;
  artifacts: ArtifactSummary[];
  onChange: (config: TrainedModelConfig) => void;
  onModels: () => void;
}) {
  const chosen = artifacts.find((artifact) => artifact.id === config.artifact_id);
  const fields = config.entities ?? [];
  const threshold = Number(config.minimum_similarity ?? 0);
  return (
    <div className="flow-step-body">
      <label className="flow-field">
        <span>Model<InfoHint text="A model trained in Models. The step names it by its id, which changes whenever the model does, so a Lab run records exactly which one it used." /></span>
        <select
          aria-label="Trained model"
          value={config.artifact_id ?? ""}
          onChange={(event) => {
            const next = artifacts.find((artifact) => artifact.id === event.target.value);
            onChange({ ...config, artifact_id: event.target.value, entities: next ? next.entities : [] });
          }}
        >
          <option value="">Choose a trained model…</option>
          {artifacts.map((artifact) => (
            <option key={artifact.id} value={artifact.id}>{artifact.name} · {artifact.id.slice(0, 8)}</option>
          ))}
          {config.artifact_id && !chosen && <option value={config.artifact_id}>Unavailable · {config.artifact_id.slice(0, 8)}</option>}
        </select>
      </label>
      {chosen && (
        <fieldset className="flow-field trained-fields">
          <legend>Fields it fills</legend>
          {chosen.entities.map((name) => (
            <label key={name}>
              <input
                type="checkbox"
                checked={fields.includes(name)}
                onChange={() => onChange({ ...config, entities: fields.includes(name) ? fields.filter((field) => field !== name) : [...fields, name] })}
              />
              <span>{name}</span>
              {chosen.validation[name]?.accuracy != null && <small>{Math.round((chosen.validation[name].accuracy ?? 0) * 100)}% leave-one-out</small>}
            </label>
          ))}
        </fieldset>
      )}
      <label className="flow-threshold">
        <span>Accept from<InfoHint text="Below this similarity to the nearest labelled document, the field is left empty with the reason. 0 accepts every prediction. The Lab's coverage curve shows what each threshold would keep and how often it is right." align="end" /></span>
        <input type="range" aria-label="Minimum similarity to the nearest document" min={0} max={1} step={0.01} value={threshold}
          onChange={(event) => onChange({ ...config, minimum_similarity: Number(event.target.value) })} />
        <output>{threshold.toFixed(2)}</output>
      </label>
      <p className="field-help">
        {chosen
          ? `Learned from ${chosen.documents} documents of ${chosen.datasets.join(", ")}, read by ${chosen.reader.map(stepLabel).join(" → ")}. Serve it text read the same way. Runs on this machine.`
          : artifacts.length ? "Choose the model this step predicts with." : "No model has been trained yet."}
        {" "}<button type="button" className="link-button" onClick={onModels}>Open Models</button>
      </p>
    </div>
  );
}

const whenLabels: Record<RegexRule["when"], string> = {
  always: "Always",
  if_empty: "Only if the model returned nothing",
  if_low_confidence: "Only if the model was unsure",
};

const sourceLabels: Record<RegexRule["source"], string> = {
  value: "What the model returned",
  text: "The document text",
};

// Every measure normalizes both names first — accents folded, punctuation
// dropped, legal forms like S.r.l. or Ltd removed — then scores what is left
// from 0 to 1. One list, so the options and their explanations cannot drift.
const algorithms = [
  {
    value: "combined",
    label: "Best of all of them",
    explanation:
      "Takes the highest score any of the others gives, so one kind of noise cannot hide a match another kind would have found. Note it inherits Jaro-Winkler's floor: unrelated names still score around 0.4, so keep the threshold well above that.",
  },
  {
    value: "exact",
    label: "Exact match",
    explanation:
      "The two normalized names are the same string, or they are not: 1 or 0, nothing between. Use it when the register is authoritative and a near miss should be looked at by a person rather than guessed at.",
  },
  {
    value: "token_set",
    label: "Shared words",
    explanation:
      "Sørensen-Dice over the sets of words: twice the words in common, over the total number of words. Order and repeats do not matter, so “Rossi Trasporti” matches “Trasporti Rossi S.r.l.”. Blind to a typo inside a word.",
  },
  {
    value: "trigram",
    label: "Shared letter triples",
    explanation:
      "The same Sørensen-Dice, over the sets of three-letter sequences instead of words. A misread letter only spoils the three triples that contain it, so it survives OCR noise, and a word that moved keeps its triples. Weak on very short names, which have few.",
  },
  {
    value: "levenshtein",
    label: "Edit distance",
    explanation:
      "1 minus the edit distance divided by the longer name: how many single-character insertions, deletions and substitutions it would take to turn one name into the other. The strictest measure of “almost the same text”, and it charges twice for two letters swapped.",
  },
  {
    value: "jaro_winkler",
    label: "Jaro-Winkler",
    explanation:
      "The classic for names: counts characters matching within a sliding window, charges half for transpositions, then adds a bonus for a shared prefix, because names that start alike usually are alike. Best on short names and swapped letters, and generous — unrelated names score around 0.4.",
  },
] as const;

function algorithmFor(value: string | undefined) {
  return algorithms.find((algorithm) => algorithm.value === value) ?? algorithms[0];
}

/** Compose the steps a document goes through, and save that as a pipeline. */
export function Pipelines({ draftSettings, entities, onUse, onProcessors, onModels }: Props) {
  const [processors, setProcessors] = useState<import("../lib/types").ProcessorRecord[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([]);
  const [pipelines, setPipelines] = useState<SavedPipeline[]>([]);
  const [catalogue, setCatalogue] = useState<StepCatalogueEntry[]>([]);
  const [draft, setDraft] = useState<PipelineDefinition | null>(null);
  const [openedAs, setOpenedAs] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [tables, setTables] = useState<{ key: string; label: string }[]>([]);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [pageLimitInput, setPageLimitInput] = useState("10");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [insertionAt, setInsertionAt] = useState<number | null>(null);
  const [paletteSearch, setPaletteSearch] = useState("");
  const [libraryOpen, setLibraryOpen] = useState(true);
  const [canvasRevision, setCanvasRevision] = useState(0);
  const [pendingChange, setPendingChange] = useState<{ perform: () => void } | null>(null);
  const discardDialog = useRef<HTMLDialogElement>(null);

  const inUse = draftSettings.pipeline;
  const entityNames = entities.map((entity) => entity.name);
  const modelEntities = entities.filter((entity) => (entity.source ?? "model") === "model");
  const derivedEntityNames = entities
    .filter((entity) => entity.source === "derived")
    .map((entity) => entity.name);
  const original = pipelines.find(pipeline => pipeline.name === openedAs);
  const hasChanges = draft !== null && (!original || draft.name !== original.name || draft.description !== original.description || draft.page_limit !== original.page_limit || JSON.stringify(draft.steps) !== JSON.stringify(original.steps));

  function changeEditor(perform: () => void) {
    if (hasChanges) setPendingChange({ perform });
    else perform();
  }

  useEffect(() => {
    if (pendingChange) discardDialog.current?.showModal();
  }, [pendingChange]);

  async function refresh() {
    setPipelines(await api.pipelines());
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [saved, steps, found, resources, trained] = await Promise.all([
          api.pipelines(),
          api.pipelineSteps(),
          api.masterDataTables(),
          api.processors(),
          api.artifacts(),
        ]);
        if (!active) return;
        setPipelines(saved);
        setProcessors(resources);
        setArtifacts(trained);
        setCatalogue(steps);
        setTables(found);
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
        .then((checked) => {
          if (!active) return;
          setCheckError(null);
          setProblems(checked.problems);
          setWarnings(checked.warnings);
        })
        // Not "no problems": the check did not happen. The previous result
        // stays, and saving still runs the same check.
        .catch((cause) => active && setCheckError(cause instanceof Error ? cause.message : String(cause)));
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [draft]);

  function open(pipeline: SavedPipeline) {
    setDraft({
      name: pipeline.name,
      description: pipeline.description,
      page_limit: pipeline.page_limit,
      steps: pipeline.steps,
    });
    setPageLimitInput(String(pipeline.page_limit));
    setOpenedAs(pipeline.name);
    setProblems(pipeline.problems);
    setWarnings(pipeline.warnings);
    setError(null);
    setState("idle");
    setSelectedIndex(null);
    setInsertionAt(null);
    setCanvasRevision(revision => revision + 1);
    setLibraryOpen(false);
  }

  function startNew() {
    const existing = new Set(pipelines.map((pipeline) => pipeline.name));
    let name = "New pipeline";
    let suffix = 1;
    while (existing.has(name)) name = `New pipeline ${++suffix}`;
    setDraft({
      name,
      description: "",
      page_limit: 10,
      steps: [
        { kind: "render_pages", config: { scale: 1.35 } },
        { kind: "llm_extract", config: {} },
      ],
    });
    setPageLimitInput("10");
    setOpenedAs(null);
    setError(null);
    setProblems([]);
    setWarnings([]);
    setCheckError(null);
    setState("idle");
    setSelectedIndex(null);
    setInsertionAt(null);
    setCanvasRevision(revision => revision + 1);
    setLibraryOpen(false);
  }

  function manageProcessors() {
    changeEditor(onProcessors);
  }

  function setSteps(steps: PipelineStep[]) {
    if (draft && state !== "saving") setDraft({ ...draft, steps });
  }

  function selectStep(index: number | null) {
    setSelectedIndex(index);
    setInsertionAt(null);
  }

  function showPalette(at: number) {
    setInsertionAt(at);
    setSelectedIndex(null);
    setPaletteSearch("");
  }

  function insertStep(kind: StepKind) {
    if (!draft || insertionAt === null) return;
    setSteps(insertFlowStep(draft.steps, insertionAt, kind));
    setSelectedIndex(insertionAt);
    setInsertionAt(null);
    setCanvasRevision(revision => revision + 1);
  }

  function reorderStep(index: number, offset: number) {
    if (!draft) return;
    setSteps(moveStep(draft.steps, index, offset));
    setSelectedIndex(index + offset);
    setCanvasRevision(revision => revision + 1);
  }

  function deleteStep(index: number) {
    if (!draft) return;
    setSteps(removeStep(draft.steps, index));
    setSelectedIndex(null);
    setCanvasRevision(revision => revision + 1);
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
      setWarnings(saved.warnings);
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

  async function rename(name: string, discarded = false) {
    if (openedAs === name && hasChanges && !discarded) {
      changeEditor(() => void rename(name, true));
      return;
    }
    const next = renameValue.trim();
    setRenaming(null);
    if (!next || next === name) return;
    setError(null);
    try {
      const renamed = await api.renamePipeline(name, next);
      await refresh();
      // The backend carried the selection across; say so here too, or the
      // chip in the top bar keeps naming a pipeline that no longer exists.
      if (inUse === name) await onUse(renamed.name);
      if (openedAs === name) open(renamed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  function duplicate(pipeline: SavedPipeline) {
    const existing = new Set(pipelines.map((candidate) => candidate.name));
    let name = `${pipeline.name} copy`;
    let suffix = 1;
    while (existing.has(name)) name = `${pipeline.name} copy ${++suffix}`;
    // Opened, not saved: a copy nobody wanted should leave nothing behind.
    open({ ...pipeline, name });
    setOpenedAs(null);
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
    <section className="settings-layout wide pipeline-page">
      <div className="settings-intro">
        <Workflow size={19} />
        <div>
          <h2>Pipelines</h2>
          <p>Build an extraction flow. Compose document readers, models and rules in execution order.</p>
        </div>
      </div>

      {error && (
        <div className="alert error-alert" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      )}

      {pendingChange && (
        <dialog className="pipeline-discard-dialog" ref={discardDialog} aria-labelledby="pipeline-discard-title" aria-describedby="pipeline-discard-description" onCancel={() => setPendingChange(null)}>
          <span className="settings-card-icon"><Workflow size={20} /></span>
          <h3 id="pipeline-discard-title">Keep your changes?</h3>
          <p id="pipeline-discard-description">There are unsaved changes to <strong>{draft?.name || "this pipeline"}</strong>. Discard them to leave this flow.</p>
          <div>
            <button className="primary-button" onClick={() => setPendingChange(null)}>Keep editing</button>
            <button className="secondary-button danger" onClick={() => { const perform = pendingChange.perform; setPendingChange(null); perform(); }}>Discard changes</button>
          </div>
        </dialog>
      )}

      <div className="settings-card pipeline-library">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Workflow size={18} /></span>
          <div>
            <h3>Saved pipelines <span className="pipeline-count">{pipelines.length}</span></h3>
            <p>Extraction, test runs and labelling all use the one marked in use.</p>
          </div>
          <button className="secondary-button small" aria-expanded={libraryOpen} aria-controls="pipeline-library-list" onClick={() => setLibraryOpen(!libraryOpen)}>{libraryOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{libraryOpen ? "Hide list" : "Browse"}</button>
          <button className="add-entity-button" disabled={state === "saving"} onClick={() => changeEditor(startNew)}><Plus size={14} /> New pipeline</button>
        </div>

        <div className="dataset-list" id="pipeline-library-list" hidden={!libraryOpen}>
          {pipelines.map((pipeline) => (
            <div className={`flow-option ${openedAs === pipeline.name ? "selected" : ""}`} key={pipeline.name}>
              {confirmingDelete === pipeline.name ? (
              <div className="row-confirm">
                <span><strong>Delete {pipeline.name}?</strong> Runs already recorded keep its name.</span>
                <button className="secondary-button small ghost" onClick={() => setConfirmingDelete(null)}>Cancel</button>
                <button className="secondary-button small danger" onClick={() => void remove(pipeline.name)}><Trash2 size={13} /> Delete</button>
              </div>
              ) : renaming === pipeline.name ? (
              <form
                className="rename-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void rename(pipeline.name);
                }}
              >
                {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
                <input autoFocus value={renameValue} onChange={(event) => setRenameValue(event.target.value)} aria-label={`New name for ${pipeline.name}`} />
                <button type="submit" className="secondary-button small"><Check size={13} /> Save</button>
                <button type="button" className="secondary-button small ghost" onClick={() => setRenaming(null)}>Cancel</button>
              </form>
              ) : (
              <>
              <button className="flow-open" disabled={state === "saving"} onClick={() => changeEditor(() => open(pipeline))}>
                <strong>{pipeline.name}</strong>
                <small>
                  {pipeline.steps.map((step) => summarizeStep(step)).join(" → ")}
                  {pipeline.description ? ` · ${pipeline.description}` : ""}
                </small>
              </button>
              {pipeline.problems.length > 0 ? (
                <span className="status-tag failed">Cannot run</span>
              ) : pipeline.warnings.length > 0 ? (
                <span className="status-tag partial" title={pipeline.warnings.join(" ")}>Warnings</span>
              ) : null}
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
                className="icon-button neutral"
                aria-label={`Rename ${pipeline.name}`}
                title="Rename"
                onClick={() => { setRenaming(pipeline.name); setRenameValue(pipeline.name); }}
              >
                <Pencil size={15} />
              </button>
              <button
                className="icon-button neutral"
                aria-label={`Duplicate ${pipeline.name}`}
                title="Duplicate"
                onClick={() => changeEditor(() => duplicate(pipeline))}
              >
                <Copy size={15} />
              </button>
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
        <div className="settings-card pipeline-editor">
          <div className="settings-card-heading">
            <span className="settings-card-icon"><Workflow size={18} /></span>
            <div>
              <h3>{draft.name || "Untitled pipeline"}</h3>
              <p>Each step reads what the previous steps produced. Saving keeps this flow available for extraction and Lab.</p>
            </div>
          </div>

          <div className="flow-identity">
            <div>
              <label className="input-label" htmlFor="pipeline-name">Name</label>
              <input
                id="pipeline-name"
                className="text-input"
                disabled={state === "saving"}
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
                disabled={state === "saving"}
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              />
            </div>
            <div>
              <label className="input-label" htmlFor="pipeline-pages">
                <Scissors size={12} /> Pages
                <InfoHint text="Process at most the first N pages of each document. The number of service calls depends on the pipeline steps." />
              </label>
              <input
                id="pipeline-pages"
                aria-label="Maximum pages"
                className="text-input"
                type="number"
                disabled={state === "saving"}
                min={MIN_PAGES}
                max={MAX_PAGES}
                step={1}
                value={pageLimitInput}
                onChange={(event) => {
                  const value = event.target.value;
                  setPageLimitInput(value);
                  if (pageLimitProblem(value) === null) setDraft({ ...draft, page_limit: Number(value) });
                }}
                onBlur={() => {
                  if (pageLimitProblem(pageLimitInput) !== null) setPageLimitInput(String(draft.page_limit));
                }}
              />
            </div>
          </div>

          {savedUnderAnotherName && (
            <p className="field-help"><Copy size={12} /> Saving now creates a copy called <strong>{draft.name}</strong>; <strong>{openedAs}</strong> stays as it is. To rename instead, use the pencil in the list above.</p>
          )}

          <div className={`pipeline-workbench ${selectedIndex !== null || insertionAt !== null ? "has-inspector" : ""}`}>
            <PipelineCanvas
              key={canvasRevision}
              steps={draft.steps} catalogue={catalogue} processors={processors} artifacts={artifacts}
              model={draftSettings.model} problems={problems} selectedIndex={selectedIndex}
              disabled={state === "saving"} onSelect={selectStep} onInsert={showPalette}
            />
            <aside className="pipeline-inspector" aria-label="Step configuration" hidden={selectedIndex === null && insertionAt === null}>
              {insertionAt !== null ? (
                <>
                  <div className="pipeline-inspector-heading">
                    <div><span>BUILD YOUR FLOW</span><h4>Add a step</h4></div>
                    <button className="icon-button neutral" aria-label="Close step picker" onClick={() => setInsertionAt(null)}><X size={16} /></button>
                  </div>
                  <p className="field-help">{insertionAt === 0 ? "Before the first step" : `After step ${insertionAt}: ${stepLabel(draft.steps[insertionAt - 1].kind)}`}</p>
                  <label className="pipeline-step-search"><Search size={15} /><input aria-label="Search steps" placeholder="Find a step…" value={paletteSearch} onChange={event => setPaletteSearch(event.target.value)} /></label>
                  <div className="pipeline-palette">
                    {groupCatalogue(catalogue.filter(entry => `${entry.label} ${entry.description}`.toLowerCase().includes(paletteSearch.toLowerCase().trim()))).map(group => (
                      <div className="pipeline-palette-group" key={group.title}>
                        <h5>{group.title}</h5>
                        {group.entries.map(entry => {
                          const kind = entry.kind as StepKind;
                          const Icon = STEP_ICONS[kind] ?? Workflow;
                          return <button className={`pipeline-palette-entry tone-${flowCategory(kind)}`} key={entry.kind} disabled={state === "saving"} onClick={() => insertStep(kind)}>
                            <span className="pipeline-node-icon"><Icon size={19} /></span>
                            <span><strong>{entry.label}</strong><small>{catalogue.find(item => item.kind === entry.kind)?.description}</small></span>
                            <Plus size={14} />
                          </button>;
                        })}
                      </div>
                    ))}
                    {!catalogue.some(entry => `${entry.label} ${entry.description}`.toLowerCase().includes(paletteSearch.toLowerCase().trim())) && <p className="field-help">No steps match this search.</p>}
                  </div>
                </>
              ) : null}
              <fieldset className="pipeline-config-fields" disabled={state === "saving"}>
                <legend className="sr-only">Selected step settings</legend>
            {draft.steps.map((step, index) => {
              if (index !== selectedIndex) return null;
              const contract = catalogue.find((entry) => entry.kind === step.kind);
              const rules = rulesOf(step);
              return (
                <div className="flow-step" key={`${step.kind}-${index}`}>
                  <div className="pipeline-inspector-heading">
                    <div><span>STEP {index + 1} · SETTINGS</span><h4>{contract?.label ?? stepLabel(step.kind)}</h4></div>
                    <button className="icon-button neutral" aria-label="Close step settings" onClick={() => selectStep(null)}><X size={16} /></button>
                  </div>
                  <p className="pipeline-step-description">{contract?.description}</p>
                  <div className="pipeline-step-actions">
                    <button className="secondary-button small" title="Move earlier in execution order" disabled={index === 0} onClick={() => reorderStep(index, -1)}><ArrowUp size={13} /> Earlier</button>
                    <button className="secondary-button small" title="Move later in execution order" disabled={index === draft.steps.length - 1} onClick={() => reorderStep(index, 1)}><ArrowDown size={13} /> Later</button>
                    <button className="icon-button" title="Remove this step" aria-label="Remove step" onClick={() => deleteStep(index)}><Trash2 size={15} /></button>
                  </div>
                  {stepProblems(problems, index).length > 0 && <div className="alert error-alert" role="status"><AlertCircle size={15} /><span>{stepProblems(problems, index).join(" ")}</span></div>}

                  {step.kind === "render_pages" && (
                    <div className="flow-step-body">
                      <label className="flow-field">
                        <span>Zoom<InfoHint text="Scale used to render PDF pages as images. 1.35 is about 97 DPI. Larger values produce more pixels and increase image size." /></span>
                        <input
                          type="number"
                          aria-label="Render zoom"
                          min={0.5}
                          max={4}
                          step={0.05}
                          value={Number((step.config as { scale?: number }).scale ?? 1.35)}
                          onChange={(event) => setSteps(setStepConfig(draft.steps, index, { scale: Number(event.target.value) }))}
                        />
                      </label>
                      <p className="field-help">Higher zoom reads small print better, and costs more memory and time.</p>
                    </div>
                  )}

                  {step.kind.startsWith("document_ai_") && <ProcessorPicker step={step} processors={processors} gcp={draftSettings.gcp} onChange={config => setSteps(patchStepConfig(draft.steps, index, config))} onManage={manageProcessors}/>}

                  {step.kind === "llm_extract" && (
                    <div className="flow-step-body">
                      <p className="field-help">Uses the model selected in LLM and the prompts written in Extraction. One call per document.</p>
                    </div>
                  )}

                  {step.kind === "read_pdf_text" && (() => {
                    const feedsModel = (step.config as { feeds_model?: boolean }).feeds_model !== false;
                    return (
                    <div className="flow-step-body">
                      <label className="flow-field">
                        <span>What this reading is for<InfoHint text="A native PDF carries its text and word positions. Choose positions only to enable document highlighting while keeping page images as the model input." /></span>
                        <select
                          aria-label="PDF text use"
                          value={feedsModel ? "text_and_positions" : "positions_only"}
                          onChange={(event) =>
                            setSteps(patchStepConfig(draft.steps, index, {
                              feeds_model: event.target.value === "text_and_positions",
                            }))
                          }
                        >
                          <option value="text_and_positions">Give the model the text, and locate values</option>
                          <option value="positions_only">Locate values only, do not give the model the text</option>
                        </select>
                      </label>
                      <p className="field-help">
                        Read on this machine, at no cost. A scanned document carries no text and is
                        refused rather than read as empty, unless a Document AI OCR step after this
                        one is set to read it; a page without text is named as such.
                        Embedded text can differ from what the page shows, so compare it with OCR
                        in Lab before relying on it.
                      </p>
                    </div>
                    );
                  })()}

                  {step.kind === "document_ai_ocr" && (() => {
                    const feedsModel = (step.config as { feeds_model?: boolean }).feeds_model !== false;
                    const onlyWithoutText = isPdfTextFallback(step);
                    return (
                    <div className="flow-step-body">
                      <label className="flow-field">
                        <span>Which documents it reads<InfoHint text="Set after Read PDF text, OCR can read only the PDFs that carry no text of their own, such as scans. The others are not sent to Google and not billed." /></span>
                        <select
                          aria-label="OCR document scope"
                          value={onlyWithoutText ? "without_pdf_text" : "every_document"}
                          onChange={(event) =>
                            setSteps(patchStepConfig(draft.steps, index, {
                              [OCR_ONLY_WITHOUT_PDF_TEXT]: event.target.value === "without_pdf_text",
                            }))
                          }
                        >
                          <option value="every_document">Every document</option>
                          <option value="without_pdf_text">Only a PDF that carries no text of its own</option>
                        </select>
                      </label>
                      <label className="flow-field">
                        <span>What this reading is for<InfoHint text="OCR returns text and word positions. Choose positions only to enable document highlighting while keeping page images as the model input." /></span>
                        <select
                          aria-label="OCR text use"
                          value={feedsModel ? "text_and_positions" : "positions_only"}
                          onChange={(event) =>
                            setSteps(patchStepConfig(draft.steps, index, {
                              feeds_model: event.target.value === "text_and_positions",
                            }))
                          }
                        >
                          <option value="text_and_positions">Give the model the text, and locate values</option>
                          <option value="positions_only">Locate values only, do not give the model the text</option>
                        </select>
                      </label>
                      <p className="field-help">
                        {feedsModel
                          ? "The model is shown the OCR text, and every value it returns is looked for on the page."
                          : "The model is not shown this text — it reads the page some other way — and the reading is used only to find where each value sits."}
                        {" "}Uses the processor selected above. Billed by Google per page, so
                        only the pages this pipeline allows are sent.
                        {onlyWithoutText && " A PDF that Read PDF text found text on is not sent at all."}
                      </p>
                    </div>
                    );
                  })()}

                  {step.kind === "document_ai_extract" && (
                    <div className="flow-step-body">
                      <p className="field-help">
                        Reads the fields configured in <strong>Extraction</strong> itself, so it
                        replaces the model call rather than feeding it — a pipeline built on this
                        needs no LLM extraction step. Field definitions are sent with each request
                        to the configured Google Cloud processor.
                      </p>
                      <p className="field-help">
                        Confidence comes from the processor rather than from a model being asked how
                        sure it is, and every value arrives with the box it sits in, so highlighting
                        works without a separate OCR step. Uses the processor selected above
                        and is billed by Google per page.
                      </p>
                    </div>
                  )}

                  {step.kind === "document_ai_layout" && (
                    <div className="flow-step-body">
                      <p className="field-help">
                        Uses the Layout Parser selected above. Costs more per page than OCR
                        and keeps the headings, tables and lists around the text.
                      </p>
                    </div>
                  )}

                  {step.kind === "artifact_predict" && (
                    <TrainedModelSettings
                      config={step.config as TrainedModelConfig}
                      artifacts={artifacts}
                      onChange={(config) => setSteps(setStepConfig(draft.steps, index, config))}
                      onModels={onModels}
                    />
                  )}

                  {step.kind === "resolve_candidates" && (
                    <ResolveSettings
                      config={resolutionOf(step.config)}
                      methods={upstreamMethods(draft.steps, index, artifacts)}
                      fields={entityNames}
                      onChange={(config) => setSteps(setStepConfig(draft.steps, index, config as unknown as Record<string, unknown>))}
                    />
                  )}

                  {step.kind === "supplier_rules" && (
                    <div className="flow-step-body">
                      <p className="field-help">
                        Applies the corrections written for whichever supplier this document turned
                        out to be from. They are set in <strong>Master Data</strong>, on the supplier
                        itself — the Rules button beside each row. Place this step after the master
                        data lookup, since it keys on the id that lookup fills in.
                      </p>
                    </div>
                  )}

                  {step.kind === "master_data_lookup" && (() => {
                    const config = step.config as {
                      table?: string;
                      source_entity?: string;
                      target_entity?: string;
                      algorithm?: string;
                      minimum_similarity?: number;
                    };
                    const update = (change: Record<string, unknown>) =>
                      setSteps(setStepConfig(draft.steps, index, { ...config, ...change }));
                    const threshold = Number(config.minimum_similarity ?? DEFAULT_MINIMUM_SIMILARITY);
                    return (
                      <div className="flow-step-body">
                        <div className="flow-lookup">
                          <label>
                            <span>Match this field
                              <InfoHint text="The extracted value that is compared with the register, usually the supplier name as printed on the document." />
                            </span>
                            <select aria-label="Match this field" value={config.source_entity ?? ""} onChange={(event) => update({ source_entity: event.target.value })}>
                              <option value="">Choose a field…</option>
                              {modelEntities.map((entity) => (
                                <option key={entity.name} value={entity.name}>{entity.name}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>Against
                              <InfoHint text="The reference table to search. Manage its rows in Master Data." />
                            </span>
                            <select
                              value={config.table ?? "suppliers"}
                              onChange={(event) => update({ table: event.target.value })}
                            >
                              {tables.map((table) => (
                                <option key={table.key} value={table.key}>{table.label}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>Fill this field
                              <InfoHint text="Where the matched row's identifier is written. Only a derived entity can be chosen: an extracted one is the model's answer and this step must not overwrite it." />
                            </span>
                            <select aria-label="Fill this field" value={config.target_entity ?? ""} onChange={(event) => update({ target_entity: event.target.value })}>
                              <option value="">Choose a field…</option>
                              {derivedEntityNames.map((name) => (
                                <option key={name} value={name}>{name}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>Compare by
                              <InfoHint text="How close two names have to be counted. Every measure normalizes both first, then scores from 0 to 1; the one you pick is explained under it, and the threshold beside it decides what counts as a match." align="end" />
                            </span>
                            <select aria-label="Compare by" value={config.algorithm ?? "combined"} onChange={(event) => update({ algorithm: event.target.value })}>
                              {algorithms.map((algorithm) => (
                                <option key={algorithm.value} value={algorithm.value}>{algorithm.label}</option>
                              ))}
                            </select>
                          </label>
                          <label className="flow-threshold">
                            <span>Accept from
                              <InfoHint text="Matches below this score leave the derived field empty. Similarity scores range from 0 to 1." align="end" />
                            </span>
                            <input
                              type="range"
                              aria-label="Minimum similarity"
                              min={0}
                              max={1}
                              step={0.01}
                              value={threshold}
                              onChange={(event) => update({ minimum_similarity: Number(event.target.value) })}
                            />
                            <output>{threshold.toFixed(2)}</output>
                          </label>
                        </div>
                        <p className="field-help flow-algorithm-note">
                          <strong>{algorithmFor(config.algorithm).label}:</strong>{" "}
                          {algorithmFor(config.algorithm).explanation}
                        </p>
                        {derivedEntityNames.length === 0 && (
                          <p className="field-help">
                            There is no derived entity to fill yet. Create one in Extraction, under
                            &ldquo;Derived&rdquo;.
                          </p>
                        )}
                      </div>
                    );
                  })()}

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
                              <label><span>Find
                                <InfoHint text="A regular expression. Round brackets mark a part you can keep on its own, for example Invoice (INV-\d+)." />
                              </span>
                                <input aria-label="Find pattern" value={rule.pattern} placeholder="\s*-\s*" onChange={(event) => update({ pattern: event.target.value })} />
                              </label>
                              <label><span>Then
                                <InfoHint text="Replace rewrites the matched text and leaves the rest. Keep throws the rest away and keeps only the match, or the part in brackets you choose." align="end" />
                              </span>
                                <select
                                  aria-label="Rule action"
                                  value={rule.group === null ? "replace" : "keep"}
                                  onChange={(event) => update(event.target.value === "replace" ? { group: null } : { group: 1, replacement: "" })}
                                >
                                  <option value="replace">Replace what matched</option>
                                  <option value="keep">Keep only what matched</option>
                                </select>
                              </label>
                              {rule.group === null ? (
                                <label><span>With</span>
                                  <input
                                    value={rule.replacement}
                                    placeholder="(nothing)"
                                    onChange={(event) => update({ replacement: event.target.value })}
                                  />
                                </label>
                              ) : (
                                <label><span>Which part
                                  <InfoHint text="0 keeps the whole match. 1 keeps what the first pair of brackets matched, 2 the second, and so on." align="end" />
                                </span>
                                  <select aria-label="Capture group" value={rule.group} onChange={(event) => update({ group: Number(event.target.value) })}>
                                    <option value={0}>The whole match</option>
                                    <option value={1}>1st bracket</option>
                                    <option value={2}>2nd bracket</option>
                                    <option value={3}>3rd bracket</option>
                                  </select>
                                </label>
                              )}
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
                          Rules run in order, and the result is checked against the field format exactly
                          like a model answer: a rule cannot put an unusable value into a field.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
              </fieldset>
            </aside>
          </div>

          {problems.length > 0 && (
            <div className="alert error-alert" role="status">
              <AlertCircle size={17} />
              <span>{problems.join(" ")}</span>
            </div>
          )}

          {warnings.length > 0 && (
            <div className="alert warning-alert" role="status">
              <Info size={17} />
              <span>{warnings.join(" ")}</span>
            </div>
          )}

          {checkError && (
            <div className="alert warning-alert" role="status">
              <AlertCircle size={17} />
              <span>This pipeline could not be checked: {checkError}</span>
            </div>
          )}

          <div className="settings-actions">
            <p><Workflow size={14} /> {hasChanges ? "Unsaved changes" : "All changes saved"} · {inUse === draft.name ? "Pipeline in use" : "Use the saved pipeline from the list above"}</p>
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
