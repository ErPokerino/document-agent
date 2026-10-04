"use client";

import {
  AlertCircle,
  CircleDot,
  Cloud,
  FileKey,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { InfoHint } from "../components/info-hint";
import type { AppSettings, GcpKeyStatus } from "../../lib/types";

type Props = {
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
};

/** Where the Document AI key goes, and proof that it works. */
export function GcpSettingsCard({ draftSettings, setDraftSettings }: Props) {
  const [status, setStatus] = useState<GcpKeyStatus | null>(null);

  useEffect(() => {
    void api.gcpKeyStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  function setGcp(update: Partial<AppSettings["gcp"]>) {
    setDraftSettings({ ...draftSettings, gcp: { ...draftSettings.gcp, ...update } });
  }


  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon"><Cloud size={18} /></span>
        <div>
          <h3>Connection and pricing</h3>
          <p>Used by the OCR, Layout Parser and Custom Extractor steps. Billed by Google per page.</p>
        </div>
        <span className={`connection-badge ${status?.configured ? "online" : ""}`}>
          <CircleDot size={12} /> {status?.configured ? "Key found" : "No key"}
        </span>
      </div>

      <ol className="key-steps">
        <li>
          In the Google Cloud console, open <strong>IAM &amp; Admin → Service Accounts</strong> and
          create one (or open an existing one). Give it the role
          {" "}<code>Document AI API User</code> on the project below.
        </li>
        <li>
          On its <strong>Keys</strong> tab choose <strong>Add key → Create new key → JSON</strong>.
          The file downloads once and cannot be downloaded again.
        </li>
        <li>
          Save that file on this machine as:
          <code className="key-path">{status?.path ?? "backend/data/gcp-service-account.json"}</code>
          The name matters. Nothing is uploaded: the backend reads it from disk and the browser
          never sees it.
        </li>
        <li>Register processors in the catalog, then check their metadata and versions.</li>
      </ol>

      {status && !status.configured && status.problem && (
        <div className="alert error-alert" role="status">
          <AlertCircle size={17} />
          <span>{status.problem}</span>
        </div>
      )}
      {status?.configured && (
        <p className="field-help good-note">
          <FileKey size={12} /> Key for <code>{status.client_email}</code>
        </p>
      )}

      <div className="gcp-grid">
        <label>
          <span>Default project ID<InfoHint text="The Google Cloud project the processors live in, as shown in the console." /></span>
          <input
            className="text-input"
            value={draftSettings.gcp.project_id}
            placeholder="my-project-123456"
            onChange={(event) => setGcp({ project_id: event.target.value })}
          />
        </label>
        <label>
          <span>Default region<InfoHint text="Must match the processor location in Google Cloud, such as eu or us. This location determines the service endpoint." /></span>
          <input
            className="text-input"
            value={draftSettings.gcp.location}
            placeholder="eu"
            onChange={(event) => setGcp({ location: event.target.value.trim() })}
          />
        </label>
      </div>
      <p className="field-help">Defaults for registering new processors. Existing catalog entries keep their own project and region. Check metadata and versions from each processor in the catalog.</p>

      <p className="input-label prompt-label">Price per 1000 pages (USD)</p>
      <div className="pricing-grid">
        <div className="pricing-row">
          <code>OCR</code>
          <label>
            <span>Per 1000 pages</span>
            <input
              type="number" step="0.01" min="0"
              value={draftSettings.gcp.ocr_per_thousand_pages ?? ""}
              onChange={(event) => setGcp({ ocr_per_thousand_pages: event.target.value === "" ? null : Number(event.target.value) })}
            />
          </label>
        </div>
        <div className="pricing-row">
          <code>Layout Parser</code>
          <label>
            <span>Per 1000 pages</span>
            <input
              type="number" step="0.01" min="0"
              value={draftSettings.gcp.layout_per_thousand_pages ?? ""}
              onChange={(event) => setGcp({ layout_per_thousand_pages: event.target.value === "" ? null : Number(event.target.value) })}
            />
          </label>
        </div>
        <div className="pricing-row">
          <code>Custom Extractor</code>
          <label>
            <span>Per 1000 pages</span>
            <input
              type="number" step="0.01" min="0"
              placeholder="Not configured"
              value={draftSettings.gcp.custom_extractor_per_thousand_pages ?? ""}
              onChange={(event) => setGcp({ custom_extractor_per_thousand_pages: event.target.value === "" ? null : Number(event.target.value) })}
            />
          </label>
        </div>
      </div>
      <p className="field-help">
        Rates you can edit, noted on {draftSettings.gcp.pricing_checked_on}. They are not read from
        Google. A run records the pages it sent; the cost shown in Lab is worked out from these.
      </p>
    </div>
  );
}
