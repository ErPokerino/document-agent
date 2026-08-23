"use client";

import { Braces, CheckCircle2, ChevronDown, ChevronRight, LoaderCircle, Save, Sparkles } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import type { AppSettings, PromptPreview } from "../lib/types";

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
        <div><h2>Prompts</h2><p>The words used to ask the model. What to ask for is in Entities.</p></div>
      </div>

      {settingsError && <div className="alert error-alert" role="alert">{settingsError}</div>}

      <div className="settings-card prompt-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Sparkles size={18} /></span>
          <div><h3>Global prompts</h3><p>The agent, the single document request and the confidence rubric. The entity names and descriptions are appended from Entities.</p></div>
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

      <div className="settings-actions sticky-actions">
        <p><Sparkles size={14} /> Saved prompts are what a test run uses.</p>
        <button className="primary-button save-button" disabled={settingsState === "saving"} onClick={onSave}>
          {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
          {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save prompts"}
        </button>
      </div>
    </section>
  );
}
