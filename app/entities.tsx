"use client";

import { Braces, CheckCircle2, LoaderCircle, Plus, Save, Sparkles, Trash2, Workflow } from "lucide-react";

import { InfoHint } from "./info-hint";
import { SystemPrompts } from "./system-prompts";
import { formatLabels } from "../lib/format";
import type { AppSettings, EntityDefinition, EntityFormat } from "../lib/types";

type Props = {
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
  onSave: () => void;
  settingsState: "idle" | "saving" | "saved" | "error";
  settingsError: string | null;
};

type Source = EntityDefinition["source"];

const groups: { source: Source; title: string; blurb: string; hint: string; icon: typeof Sparkles }[] = [
  {
    source: "model",
    title: "Extracted",
    blurb: "Read off the page: asked of the model, constrained by the generated JSON schema.",
    hint: "These are the fields the model is shown and asked to fill. Their names, formats and descriptions build the prompt and the schema.",
    icon: Sparkles,
  },
  {
    source: "derived",
    title: "Derived",
    blurb: "Never asked of the model: a step in the pipeline fills them.",
    hint: "A field the document does not carry, like an internal supplier id. The model is never shown it; a pipeline step works it out from the other fields or from a reference table. It is still labelled and scored like any other field.",
    icon: Workflow,
  },
];

/** Everything a document produces, and where each value comes from. */
export function Entities({ draftSettings, setDraftSettings, onSave, settingsState, settingsError }: Props) {
  const entities = draftSettings.prompts.entities;

  function setEntities(next: EntityDefinition[]) {
    setDraftSettings({ ...draftSettings, prompts: { ...draftSettings.prompts, entities: next } });
  }

  function updateEntity(target: EntityDefinition, update: Partial<EntityDefinition>) {
    setEntities(entities.map((entity) => (entity === target ? { ...entity, ...update } : entity)));
  }

  function addEntity(source: Source) {
    const existing = new Set(entities.map((entity) => entity.name));
    let suffix = 1;
    let name = source === "derived" ? "new_derived_field" : "new_field";
    const base = name;
    while (existing.has(name)) name = `${base}_${++suffix}`;
    setEntities([
      ...entities,
      {
        name,
        format: "text",
        source,
        description:
          source === "derived"
            ? "What this value means, and where a pipeline step should find it."
            : "Describe where to find the value and how to interpret it.",
      },
    ]);
  }

  function removeEntity(target: EntityDefinition) {
    if (entities.length === 1) return;
    setEntities(entities.filter((entity) => entity !== target));
  }

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Braces size={19} />
        <div>
          <h2>Extraction</h2>
          <p>What a document produces, and the words used to ask the model for it.</p>
        </div>
      </div>

      {settingsError && <div className="alert error-alert" role="alert">{settingsError}</div>}

      {groups.map((group) => {
        const Icon = group.icon;
        const inGroup = entities.filter((entity) => (entity.source ?? "model") === group.source);
        return (
          <div className="settings-card entity-card" key={group.source}>
            <div className="settings-card-heading entity-heading">
              <span className="settings-card-icon"><Icon size={18} /></span>
              <div>
                <h3>{group.title}<InfoHint text={group.hint} /></h3>
                <p>{group.blurb}</p>
              </div>
              <button className="add-entity-button" onClick={() => addEntity(group.source)}>
                <Plus size={14} /> Add
              </button>
            </div>

            {inGroup.length === 0 ? (
              <p className="field-help">
                {group.source === "derived"
                  ? "None yet. A derived field is one the document never states, such as an internal identifier looked up from Master Data."
                  : "None yet, so the model would be asked for nothing."}
              </p>
            ) : (
              <div className="entity-list">
                {inGroup.map((entity) => {
                  // Keyed by position, not by name. The name is edited in the
                  // input two lines down, so keying by it gave React a new key
                  // on every keystroke: it discarded the row, built another,
                  // and the field lost focus after each letter.
                  const position = entities.indexOf(entity);
                  return (
                  <div className="entity-editor" key={position}>
                    <div className="entity-index">{position + 1}</div>
                    <div className="entity-fields">
                      <div className="entity-row">
                        <label>
                          <span>JSON name</span>
                          <input
                            value={entity.name}
                            onChange={(event) =>
                              updateEntity(entity, { name: event.target.value.toLowerCase().replaceAll(" ", "_") })
                            }
                          />
                        </label>
                        <label>
                          <span>Format</span>
                          <select
                            value={entity.format}
                            onChange={(event) => updateEntity(entity, { format: event.target.value as EntityFormat })}
                          >
                            {Object.entries(formatLabels).map(([value, label]) => (
                              <option value={value} key={value}>{label}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span>Comes from</span>
                          <select
                            value={entity.source ?? "model"}
                            onChange={(event) => updateEntity(entity, { source: event.target.value as Source })}
                          >
                            <option value="model">The model</option>
                            <option value="derived">A pipeline step</option>
                          </select>
                        </label>
                      </div>
                      <label className="entity-description">
                        <span>{group.source === "derived" ? "What this value is" : "Description for the model"}</span>
                        <textarea
                          value={entity.description}
                          onChange={(event) => updateEntity(entity, { description: event.target.value })}
                        />
                      </label>
                    </div>
                    <button
                      className="remove-entity-button"
                      disabled={entities.length === 1}
                      onClick={() => removeEntity(entity)}
                      aria-label={`Remove ${entity.name}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      <SystemPrompts draftSettings={draftSettings} setDraftSettings={setDraftSettings} />

      <div className="settings-actions sticky-actions">
        <p><Braces size={14} /> A derived field needs a pipeline step that fills it; Pipelines says so if none does.</p>
        <button className="primary-button save-button" disabled={settingsState === "saving"} onClick={onSave}>
          {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
          {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save extraction"}
        </button>
      </div>
    </section>
  );
}
