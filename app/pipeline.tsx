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
  Trash2,
  Workflow,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { InfoHint } from "./info-hint";
import {
  MAX_PAGES,
  MIN_PAGES,
  DEFAULT_MINIMUM_SIMILARITY,
  addStep,
  emptyRule,
  groupCatalogue,
  moveStep,
  pageLimitProblem,
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

// Every measure normalizes both names first — accents folded, punctuation
// dropped, legal forms like S.r.l. or Ltd removed — then scores what is left.
const algorithmHints: Record<string, string> = {
  combined:
    "The highest score any of the others gives, so one kind of noise cannot hide a match another kind would find. Unrelated names still score around 0.4, because Jaro-Winkler is in the mix: keep the threshold well above that.",
  exact:
    "The normalized names are the same string, or they are not: 1 or 0. Use it when the register is authoritative and anything less should be looked at by a person.",
  token_set:
    "Sørensen-Dice over the sets of words: twice the shared words over the total. Order and repeats do not matter, so 'Rossi Trasporti' matches 'Trasporti Rossi S.r.l.'. Blind to a typo inside a word.",
  trigram:
    "Sørensen-Dice over the sets of three-letter sequences. Survives a misread letter, and still sees a word that moved. Weak on very short names, which have few triples.",
  levenshtein:
    "1 minus the edit distance over the longer name: the number of single-character insertions, deletions and substitutions needed to turn one into the other. The strictest measure of 'almost the same text'; punishes two swapped letters twice.",
  jaro_winkler:
    "The classic name-matching measure: characters matching within a window, transpositions half-priced, plus a bonus for a shared prefix. Best on short names and swapped letters; generous, so unrelated names score around 0.4.",
};

/** Compose the steps a document goes through, and save that as a pipeline. */
export function Pipelines({ draftSettings, entities, onUse }: Props) {
  const [pipelines, setPipelines] = useState<SavedPipeline[]>([]);
  const [catalogue, setCatalogue] = useState<StepCatalogueEntry[]>([]);
  const [draft, setDraft] = useState<PipelineDefinition | null>(null);
  const [openedAs, setOpenedAs] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [tables, setTables] = useState<{ key: string; label: string }[]>([]);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [pageLimitInput, setPageLimitInput] = useState("10");
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);

  const inUse = draftSettings.pipeline;
  const entityNames = entities.map((entity) => entity.name);
  const modelEntities = entities.filter((entity) => (entity.source ?? "model") === "model");
  const derivedEntityNames = entities
    .filter((entity) => entity.source === "derived")
    .map((entity) => entity.name);

  async function refresh() {
    setPipelines(await api.pipelines());
  }

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [saved, steps, found] = await Promise.all([
          api.pipelines(),
          api.pipelineSteps(),
          api.masterDataTables(),
        ]);
        if (!active) return;
        setPipelines(saved);
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
          setProblems(checked.problems);
          setWarnings(checked.warnings);
        })
        .catch(() => active && setProblems([]));
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

  async function rename(name: string) {
    const next = renameValue.trim();
    setRenaming(null);
    if (!next || next === name) return;
    setError(null);
    try {
      const renamed = await api.renamePipeline(name, next);
      await refresh();
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
              <button className="flow-open" onClick={() => open(pipeline)}>
                <strong>{pipeline.name}</strong>
                <small>
                  {pipeline.steps.map((step) => summarizeStep(step)).join(" → ")}
                  {pipeline.description ? ` · ${pipeline.description}` : ""}
                </small>
              </button>
              {pipeline.problems.length > 0 ? (
                <span className="status-tag failed">Cannot run</span>
              ) : pipeline.warnings.length > 0 ? (
                <span className="status-tag partial" title={pipeline.warnings.join(" ")}>Partial</span>
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
                onClick={() => duplicate(pipeline)}
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
            <div>
              <label className="input-label" htmlFor="pipeline-pages">
                <Scissors size={12} /> Pages
                <InfoHint text="How many of the first pages this pipeline looks at. Pages 1–N go out in one call; the app never merges separate page extractions." />
              </label>
              <input
                id="pipeline-pages"
                className="text-input"
                type="number"
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
                        <span>Zoom<InfoHint text="How large the page is drawn before it is sent. 1.35 is about 130 DPI." /></span>
                        <input
                          type="number"
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

                  {step.kind === "llm_extract" && (
                    <div className="flow-step-body">
                      <p className="field-help">Uses the model selected in Models and the prompts written in Prompts. One call per document.</p>
                    </div>
                  )}

                  {step.kind === "document_ai_ocr" && (
                    <div className="flow-step-body">
                      <p className="field-help">
                        Uses the OCR processor configured in Settings. Billed by Google per page, so
                        only the pages this pipeline allows are sent.
                      </p>
                    </div>
                  )}

                  {step.kind === "document_ai_layout" && (
                    <div className="flow-step-body">
                      <p className="field-help">
                        Uses the Layout Parser configured in Settings. Costs more per page than OCR
                        and keeps the headings, tables and lists around the text.
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
                            <select value={config.source_entity ?? ""} onChange={(event) => update({ source_entity: event.target.value })}>
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
                            <select value={config.target_entity ?? ""} onChange={(event) => update({ target_entity: event.target.value })}>
                              <option value="">Choose a field…</option>
                              {derivedEntityNames.map((name) => (
                                <option key={name} value={name}>{name}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>Compare by
                              <InfoHint text={algorithmHints[config.algorithm ?? "combined"]} align="end" />
                            </span>
                            <select value={config.algorithm ?? "combined"} onChange={(event) => update({ algorithm: event.target.value })}>
                              <option value="combined">Best of all of them</option>
                              <option value="exact">Exact match</option>
                              <option value="token_set">Shared words</option>
                              <option value="trigram">Shared letter triples</option>
                              <option value="levenshtein">Edit distance</option>
                              <option value="jaro_winkler">Jaro-Winkler</option>
                            </select>
                          </label>
                          <label className="flow-threshold">
                            <span>Accept from
                              <InfoHint text="Below this the field is left empty and the run says which score it reached, because an identifier that is wrong but looks like data is worse than a gap." align="end" />
                            </span>
                            <input
                              type="range"
                              min={0}
                              max={1}
                              step={0.01}
                              value={threshold}
                              onChange={(event) => update({ minimum_similarity: Number(event.target.value) })}
                            />
                            <output>{threshold.toFixed(2)}</output>
                          </label>
                        </div>
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
                                <input value={rule.pattern} placeholder="\s*-\s*" onChange={(event) => update({ pattern: event.target.value })} />
                              </label>
                              <label><span>Then
                                <InfoHint text="Replace rewrites the matched text and leaves the rest. Keep throws the rest away and keeps only the match, or the part in brackets you choose." align="end" />
                              </span>
                                <select
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
                                  <select value={rule.group} onChange={(event) => update({ group: Number(event.target.value) })}>
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
          </div>

          <div className="flow-add-step">
            {groupCatalogue(catalogue).map((group) => (
              <div className="flow-add-group" key={group.title}>
                <span className="flow-add-title">{group.title}<InfoHint text={group.blurb} /></span>
                <div className="flow-add-buttons">
                  {group.entries.map((entry) => (
                    <button
                      className="secondary-button small"
                      key={entry.kind}
                      onClick={() => setSteps(addStep(draft.steps, entry.kind as StepKind))}
                    >
                      <Plus size={13} /> {entry.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
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
