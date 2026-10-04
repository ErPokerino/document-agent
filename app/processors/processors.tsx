"use client";
import { useEffect, useState } from "react";
import { Cloud, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import type { AppSettings, DocumentProcessor, ProcessorInspection, ProcessorRecord } from "../../lib/types";
import { GcpSettingsCard } from "./gcp-settings";

export const processorLabels = { document_ai_ocr: "OCR", document_ai_layout: "Layout Parser", document_ai_extract: "Custom Extractor" };
type Props = { draftSettings: AppSettings; setDraftSettings: (settings: AppSettings) => void; onSave: () => void; settingsState: string; settingsError: string | null; onPipelines: () => void };

export function Processors({ draftSettings, setDraftSettings, onSave, settingsState, settingsError, onPipelines }: Props) {
  const [entries, setEntries] = useState<ProcessorRecord[]>([]);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<DocumentProcessor | null>(null);
  const [saving, setSaving] = useState(false);
  const [opened, setOpened] = useState<string | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, ProcessorInspection>>({});
  const [checkErrors, setCheckErrors] = useState<Record<string, string>>({});
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  useEffect(() => { let live = true; api.processors().then(rows => { if (live) setEntries(rows); }).catch(e => { if (live) setError(e.message); }).finally(() => { if (live) setLoading(false); }); return () => { live = false; }; }, []);
  const visible = entries.filter(p => (filter === "all" || p.kind === filter) && `${p.name} ${p.project_id} ${p.processor_id}`.toLowerCase().includes(query.toLowerCase()));
  async function save() {
    if (!draft) return;
    setSaving(true); setError(null);
    try { await api.saveProcessor(draft); setEntries(await api.processors()); setDraft(null); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setSaving(false); }
  }
  async function inspect(id: string) {
    setOpened(id); setChecking(id); setCheckErrors(old => ({ ...old, [id]: "" }));
    try { const result = await api.inspectProcessor(id); setChecks(old => ({ ...old, [id]: result })); } catch (e) { setCheckErrors(old => ({ ...old, [id]: e instanceof Error ? e.message : String(e) })); } finally { setChecking(null); }
  }
  async function remove(id: string) {
    setSaving(true); setError(null);
    try { await api.deleteProcessor(id); setEntries(await api.processors()); setConfirmDelete(null); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setSaving(false); }
  }
  return <section className="settings-layout wide processors-page">
    <div className="settings-intro"><Cloud size={19}/><div><h2>Processors</h2><p>Register Document AI resources here. Choose the processor and version in each pipeline step.</p></div></div>
    {(error || settingsError) && <div className="alert error-alert" role="alert">{error || settingsError}</div>}
    <div className="settings-card">
      <div className="settings-card-heading"><div><h3>Processor catalog</h3><p>Register an existing Google Cloud processor. Registration does not create or deploy resources in Google Cloud.</p></div><button className="secondary-button" disabled={!!draft || loading} onClick={() => setDraft({ id: crypto.randomUUID(), name: "", kind: "document_ai_ocr", project_id: draftSettings.gcp.project_id, location: draftSettings.gcp.location, processor_id: "" })}><Plus size={14}/> Register processor</button></div>
      <div className="resource-tabs" aria-label="Processor types">{[["all", "All"], ...Object.entries(processorLabels)].map(([key, label]) => <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label} <small>{entries.filter(p => key === "all" || p.kind === key).length}</small></button>)}</div>
      <label className="input-label" htmlFor="processor-search">Search processors</label><input id="processor-search" className="text-input" placeholder="Name, project or processor ID" value={query} onChange={e => setQuery(e.target.value)}/>
      {draft && <form className="processor-editor" onSubmit={e => { e.preventDefault(); void save(); }}>
        <h3>{entries.some(p => p.id === draft.id) ? "Rename processor" : "Register processor"}</h3>
        <div className="processor-fields">
          <label>Name<input required maxLength={100} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })}/></label>
          <label>Type<select disabled={entries.some(p => p.id === draft.id)} value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value as DocumentProcessor["kind"] })}>{Object.entries(processorLabels).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          {([['project_id','Project ID'],['location','Region'],['processor_id','Processor ID']] as const).map(([key,label]) => <label key={key}>{label}<input required disabled={entries.some(p => p.id === draft.id)} value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value.trim() })}/></label>)}
        </div>
        <div className="processor-actions"><button className="primary-button" disabled={saving}>{saving ? "Saving…" : "Save processor"}</button><button type="button" className="secondary-button" disabled={saving} onClick={() => setDraft(null)}>Cancel</button></div>
      </form>}
      {loading ? <p className="field-help" role="status">Loading processors…</p> : visible.length === 0 ? <p className="field-help">{entries.length ? "No processors match the selected type and search." : "No processors registered. Add one using its ID from Google Cloud."}</p> : <div className="processor-list">{visible.map(p => <article key={p.id} className="processor-item">
        <div className="processor-summary"><div><strong>{p.name}</strong><span className="provider-tag">{processorLabels[p.kind]}</span><p>{p.project_id} · {p.location}</p><code>{p.processor_id}</code></div><div><span>{checks[p.id] ? checks[p.id].state.replaceAll("_", " ").toLowerCase() : "Not checked"}</span><p>{p.used_by.length} pipeline{p.used_by.length === 1 ? "" : "s"}</p></div></div>
        <div className="processor-actions"><button className="secondary-button small" aria-expanded={opened === p.id} onClick={() => setOpened(opened === p.id ? null : p.id)}>{opened === p.id ? "Hide details" : "Details & versions"}</button><button className="link-button" disabled={!!draft} onClick={() => { const { used_by: _used, ...entry } = p; void _used; setDraft(entry); }}>Rename</button><button className="link-button" disabled={p.used_by.length > 0 || saving} title={p.used_by.length ? "Used by saved pipelines" : "Remove from this app; the Google Cloud resource is unchanged"} onClick={() => setConfirmDelete(p.id)}><Trash2 size={12}/> Remove</button></div>
        {confirmDelete === p.id && <div className="processor-actions"><span>Remove {p.name} from the catalog?</span><button className="secondary-button danger" disabled={saving} onClick={() => void remove(p.id)}>Remove registration</button><button className="link-button" onClick={() => setConfirmDelete(null)}>Cancel</button></div>}
        {opened === p.id && <div className="processor-details">
          <p className="field-help">{p.used_by.length ? `Used by: ${p.used_by.join(", ")}` : "No saved pipeline uses this processor."} <button className="link-button" onClick={onPipelines}>Open Pipelines</button></p>
          <button className="secondary-button small" disabled={checking !== null} onClick={() => void inspect(p.id)}><RefreshCw size={13}/>{checking === p.id ? "Checking…" : "Check metadata & versions"}</button>
          <p className="field-help">Reads metadata only. No document is processed. This checks metadata access, not permission to run an extraction.</p>
          {checkErrors[p.id] && <p role="alert" className="alert error-alert">{checkErrors[p.id]}</p>}
          {checks[p.id] && <><p className="field-help">Google name: {checks[p.id].display_name} · Checked {new Date(checks[p.id].checked_at).toLocaleString()}</p><p className="field-help">Default version: <code>{checks[p.id].default_version || "Not reported"}</code></p><div className="table-scroll"><table className="data-table"><thead><tr><th>Version</th><th>State</th></tr></thead><tbody>{checks[p.id].versions.map(v => <tr key={v.id}><td><strong>{v.name}</strong><small>{v.id}</small></td><td>{v.state.replaceAll("_", " ")}{v.id === checks[p.id].default_version ? " · Default" : ""}</td></tr>)}</tbody></table></div>{checks[p.id].versions.length === 0 && <p className="field-help">No versions returned by Google.</p>}</>}
        </div>}
      </article>)}</div>}
    </div>
    <details className="processor-connection"><summary>Connection and pricing</summary><GcpSettingsCard draftSettings={draftSettings} setDraftSettings={setDraftSettings}/><div className="settings-actions"><p className="field-help">Catalog changes are saved separately.</p><button className="primary-button" disabled={settingsState === "saving"} onClick={onSave}><Save size={14}/>{settingsState === "saving" ? "Saving…" : "Save connection & pricing"}</button></div></details>
  </section>;
}
