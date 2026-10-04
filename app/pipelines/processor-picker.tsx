"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { AppSettings, PipelineStep, ProcessorInspection, ProcessorRecord } from "../../lib/types";
import { InfoHint } from "../components/info-hint";

type Props = { step: PipelineStep; processors: ProcessorRecord[]; gcp: AppSettings["gcp"]; onChange: (config: Record<string, unknown>) => void; onManage: () => void };
export function ProcessorPicker({ step, processors, gcp, onChange, onManage }: Props) {
  const config = step.config as Record<string, unknown>;
  const ref = String(config.processor_ref || "");
  const version = String(config.processor_version || "");
  const [inspection, setInspection] = useState<{ ref: string; result: ProcessorInspection } | null>(null);
  const [error, setError] = useState<{ ref: string; message: string } | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!ref) return;
    let active = true;
    api.inspectProcessor(ref).then(result => { if (active) { setInspection({ ref, result }); setError(null); } }).catch(e => { if (active) setError({ ref, message: e.message }); });
    return () => { active = false; };
  }, [ref, revision]);
  const data = inspection?.ref === ref ? inspection.result : null;
  const problem = error?.ref === ref ? error.message : null;
  const choices = processors.filter(p => p.kind === step.kind);
  const selected = choices.find(p => p.id === ref);
  const fields = { document_ai_ocr: gcp.ocr_processor_id, document_ai_layout: gcp.layout_processor_id, document_ai_extract: gcp.custom_extractor_processor_id };
  const legacy = String(config.processor_id || fields[step.kind as keyof typeof fields] || "Not configured");
  return <div className="processor-picker">
    <div className="processor-fields">
      <label>Processor<select aria-label="Step processor" value={ref} onChange={e => onChange({ processor_ref: e.target.value, processor_version: "", processor_id: "", project_id: "", location: "" })}>
        {!ref && <option value="">{"processor_ref" in config ? "Choose a processor…" : `Existing binding: ${legacy}`}</option>}
        {ref && !selected && <option value={ref}>Unavailable processor ({ref})</option>}
        {choices.map(p => <option key={p.id} value={p.id}>{p.name} · {p.project_id} / {p.location} · {p.processor_id}</option>)}
      </select></label>
      {ref && <label>Version<InfoHint text="An explicit version keeps this step's choice stable. Processor default follows changes made in Google Cloud. Lab records the resolved version when metadata is available."/>
        <select aria-label="Processor version" value={version} onChange={e => onChange({ processor_version: e.target.value })}>
          <option value="">Processor default{data?.default_version ? ` · ${data.default_version}` : ""}</option>
          {version && !data?.versions.some(v => v.id === version) && <option value={version}>{version} · Saved version</option>}
          {data?.versions.map(v => <option key={v.id} value={v.id}>{v.name} · {v.id} · {v.state.replaceAll("_", " ")}</option>)}
        </select>
      </label>}
    </div>
    {selected && <p className="field-help">{selected.project_id} · {selected.location} · <code>{selected.processor_id}</code></p>}
    {ref && !data && !problem && <p className="field-help" role="status">Reading available versions…</p>}
    {problem && <><p className="field-help" role="status">Versions could not be read: {problem} <button className="link-button" onClick={() => setRevision(n => n + 1)}>Retry</button></p><label className="flow-field"><span>Explicit version ID (optional)</span><input value={version} onChange={e => onChange({ processor_version: e.target.value.trim() })}/></label></>}
    {ref && !version && <p className="field-help">Follows the Google Cloud default. Select an explicit version for a controlled comparison.</p>}
    <button className="link-button" onClick={onManage}>Manage processors</button>
  </div>;
}
