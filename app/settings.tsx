"use client";

import { CheckCircle2, LoaderCircle, Monitor, Moon, Save, SlidersHorizontal, Sun } from "lucide-react";

import { GcpSettingsCard } from "./gcp-settings";
import { InfoHint } from "./info-hint";
import type { AppSettings } from "../lib/types";

type Theme = AppSettings["theme"];

type Props = {
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
  onSave: () => void;
  settingsState: "idle" | "saving" | "saved" | "error";
  settingsError: string | null;
};

const themes: { value: Theme; label: string; hint: string; icon: typeof Sun }[] = [
  { value: "system", label: "System", hint: "Follow this computer's setting", icon: Monitor },
  { value: "light", label: "Light", hint: "Always light", icon: Sun },
  { value: "dark", label: "Dark", hint: "Always dark", icon: Moon },
];

/** Preferences that belong to the person using the app, not to a run. */
export function Settings({ draftSettings, setDraftSettings, onSave, settingsState, settingsError }: Props) {
  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <SlidersHorizontal size={19} />
        <div>
          <h2>Settings</h2>
          <p>How the app looks, and the credentials it uses on this machine.</p>
        </div>
      </div>

      {settingsError && <div className="alert error-alert" role="alert">{settingsError}</div>}

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Sun size={18} /></span>
          <div>
            <h3>Appearance</h3>
            <p>Applied straight away, and remembered for the next session.</p>
          </div>
        </div>

        <p className="input-label">
          Theme
          <InfoHint text="System follows what this computer asks for, and changes with it during the day." />
        </p>
        <div className="choice-row">
          {themes.map((theme) => {
            const Icon = theme.icon;
            const selected = draftSettings.theme === theme.value;
            return (
              <button
                key={theme.value}
                className={`choice-option ${selected ? "selected" : ""}`}
                aria-pressed={selected}
                onClick={() => setDraftSettings({ ...draftSettings, theme: theme.value })}
              >
                <Icon size={16} />
                <strong>{theme.label}</strong>
                <small>{theme.hint}</small>
              </button>
            );
          })}
        </div>
      </div>

      <GcpSettingsCard draftSettings={draftSettings} setDraftSettings={setDraftSettings} />

      <div className="settings-actions sticky-actions">
        <p><SlidersHorizontal size={14} /> Verify uses the settings already saved, so save first.</p>
        <button className="primary-button save-button" disabled={settingsState === "saving"} onClick={onSave}>
          {settingsState === "saving" ? <LoaderCircle className="spin" size={15} /> : settingsState === "saved" ? <CheckCircle2 size={15} /> : <Save size={15} />}
          {settingsState === "saving" ? "Saving…" : settingsState === "saved" ? "Saved" : "Save settings"}
        </button>
      </div>
    </section>
  );
}
