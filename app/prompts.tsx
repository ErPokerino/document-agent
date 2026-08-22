"use client";

import { Braces, CheckCircle2, ChevronDown, ChevronRight, LoaderCircle, Plus, Save, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import { formatLabels } from "../lib/format";
import type { AppSettings, EntityDefinition, EntityFormat, PromptPreview } from "../lib/types";

type Props = {
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
  onSave: () => void;
  settingsState: "idle" | "saving" | "saved" | "error";
  settingsError: string | null;
};

/** What to extract, and how to ask for it. */
export function Prompts({ draftSettings, setDraftSettings, onSave, settingsState, settingsError }: Props) {
  const [promptPreview, setPromptPreview] = useState<PromptPreview | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  function setPrompt(key: "system_prompt" | "user_prompt" | "confidence_prompt", value: string) {
    setDraftSettings({ ...draftSettings, prompts: { ...draftSettings.prompts, [key]: value } });
  }

  function updateEntity(index: number, update: Partial<EntityDefinition>) {
    const entities = draftSettings.prompts.entities.map((entity, entityIndex) =>
      entityIndex === index ? { ...entity, ...update } : entity,
    );
    setDraftSettings({ ...draftSettings, prompts: { ...draftSettings.prompts, entities } });
  }

  function addEntity() {
    const existing = new Set(draftSettings.prompts.entities.map((entity) => entity.name));
    let suffix = 1;
    let name = "new_field";
    while (existing.has(name)) name = `new_field_${++suffix}`;
    setDraftSettings({
      ...draftSettings,
      prompts: {
        ...draftSettings.prompts,
        entities: [
          ...draftSettings.prompts.entities,
          { name, format: "text", description: "Describe where to find the value and how to interpret it." },
        ],
      },
    });
  }

  function removeEntity(index: number) {
    if (draftSettings.prompts.entities.length === 1) return;
    setDraftSettings({
      ...draftSettings,
      prompts: {
        ...draftSettings.prompts,
        entities: draftSettings.prompts.entities.filter((_, entityIndex) => entityIndex !== index),
      },
    });
  }

  // Assembled by the backend, so it cannot drift from what actually goes out.
  function refreshPreview() {
    void api
      .previewPrompt(draftSettings.prompts, draftSettings.provider)
      .then(setPromptPreview)
      .catch(() => setPromptPreview(null));
  }

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Braces size={19} />
        <div><h2>Prompts &amp; entities</h2><p>What to pull out of a document, and the words used to ask for it.</p></div>
      </div>

      {settingsError && <div className="alert error-alert" role="alert">{settingsError}</div>}

      <div className="settings-card prompt-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Sparkles size={18} /></span>
          <div><h3>Global prompts</h3><p>Control the agent, the single document request and the confidence rubric.</p></div>
        </div>
        <div className="prompt-field">
          <div className="prompt-field-head">
            <label className="input-label" htmlFor="system-prompt">System prompt</label>
            <small className={draftSettings.prompts.system_prompt.length > 8000 ? "over" : ""}>{draftSettings.prompts.system_prompt.length} / 8000</small>
          </div>
          <p className="field-help">Who the model is and what it must never do. The entity list and the format rules are appended automatically.</p>
          <textarea id="system-prompt" className="prompt-textarea large" value={draftSettings.prompts.system_prompt} onChange={(event) => setPrompt("system_prompt", event.target.value)} />
        </div>

        <div className="prompt-pair">
        <div className="prompt-field">
          <div className="prompt-field-head">
            <label className="input-label" htmlFor="user-prompt">Extraction instructions</label>
            <small className={draftSettings.prompts.user_prompt.length > 4000 ? "over" : ""}>{draftSettings.prompts.user_prompt.length} / 4000</small>
          </div>
          <p className="field-help">Sent with the page images. <code>{"{page_range}"}</code> is replaced with the pages in the call.</p>
          <textarea id="user-prompt" className="prompt-textarea" value={draftSettings.prompts.user_prompt} onChange={(event) => setPrompt("user_prompt", event.target.value)} />
        </div>

        <div className="prompt-field">
          <div className="prompt-field-head">
            <label className="input-label" htmlFor="confidence-prompt">Confidence instructions</label>
            <small className={draftSettings.prompts.confidence_prompt.length > 4000 ? "over" : ""}>{draftSettings.prompts.confidence_prompt.length} / 4000</small>
          </div>
          <p className="field-help">How the model chooses <code>low</code>, <code>medium</code> and <code>high</code>. Test runs report how often each level was actually right.</p>
          <textarea id="confidence-prompt" className="prompt-textarea" value={draftSettings.prompts.confidence_prompt} onChange={(event) => setPrompt("confidence_prompt", event.target.value)} />
        </div>
        </div>

        <div className="prompt-preview">
          <button
            className="prompt-preview-toggle"
            aria-expanded={previewOpen}
            onClick={() => {
              const opening = !previewOpen;
              setPreviewOpen(opening);
              if (opening) refreshPreview();
            }}
          >
            {previewOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <strong>What the model actually receives</strong>
            <small>assembled by the backend</small>
          </button>
          {previewOpen && (
            <div className="prompt-preview-body">
              <p className="field-help">
                Your text above is only the opening. This is the whole system message and the schema
                the answer is constrained to, for <code>{draftSettings.provider === "gemini" ? "Gemini" : "LM Studio"}</code>.
                <button className="link-button" onClick={refreshPreview}>Refresh</button>
              </p>
              {promptPreview ? (
                <>
                  <pre className="prompt-preview-text">{promptPreview.system_prompt}</pre>
                  <details>
                    <summary>Response schema{promptPreview.output_token_budget ? ` · ${promptPreview.output_token_budget} output token budget` : ""}</summary>
                    <pre className="prompt-preview-text">{promptPreview.generation_schema}</pre>
                  </details>
                </>
              ) : (
                <p className="field-help">Save the prompts first, or check that the backend is running.</p>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="settings-card entity-card">
        <div className="settings-card-heading entity-heading">
          <span className="settings-card-icon"><Braces size={18} /></span>
          <div><h3>Entities to extract</h3><p>Name, format and description automatically build the prompt and JSON Schema.</p></div>
          <button className="add-entity-button" onClick={addEntity}><Plus size={14} /> Add entity</button>
        </div>
        <div className="entity-list">
          {draftSettings.prompts.entities.map((entity, index) => (
            <div className="entity-editor" key={`${entity.name}-${index}`}>
              <div className="entity-index">{String(index + 1).padStart(2, "0")}</div>
              <div className="entity-fields">
                <div className="entity-row">
                  <label><span>JSON name</span><input value={entity.name} onChange={(event) => updateEntity(index, { name: event.target.value.toLowerCase().replaceAll(" ", "_") })} /></label>
                  <label><span>Format</span><select value={entity.format} onChange={(event) => updateEntity(index, { format: event.target.value as EntityFormat })}>{Object.entries(formatLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
                </div>
                <label className="entity-description"><span>Description for the model</span><textarea value={entity.description} onChange={(event) => updateEntity(index, { description: event.target.value })} /></label>
              </div>
              <button className="remove-entity-button" disabled={draftSettings.prompts.entities.length === 1} onClick={() => removeEntity(index)} aria-label={`Remove ${entity.name}`}><Trash2 size={15} /></button>
            </div>
          ))}
        </div>
      </div>
  

      <div className="settings-actions sticky-actions">
        <p><Braces size={14} /> Saved prompts are what a test run uses.</p>
        <button className="primary-button save-button" disabled={settingsState === "saving"} onClick={onSave}>
          {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
          {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save prompts"}
        </button>
      </div>
    </section>
  );
}
