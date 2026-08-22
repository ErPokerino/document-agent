"use client";

import {
  AlertCircle,
  Check,
  CircleDot,
  Cloud,
  FileKey,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { InfoHint } from "./info-hint";
import type { AppSettings, GcpKeyStatus } from "../lib/types";

type Props = {
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
};

/** Where the Document AI key goes, and proof that it works. */
export function GcpSettingsCard({ draftSettings, setDraftSettings }: Props) {
  const [status, setStatus] = useState<GcpKeyStatus | null>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    void api.gcpKeyStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  function setGcp(update: Partial<AppSettings["gcp"]>) {
    setDraftSettings({ ...draftSettings, gcp: { ...draftSettings.gcp, ...update } });
  }

  const verified = status?.verified_processors ?? [];

  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon"><Cloud size={18} /></span>
        <div>
          <h3>Google Document AI</h3>
          <p>Used by the OCR and Layout Parser steps. Billed by Google per page.</p>
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
        <li>Fill in the project and the two processor ids, save, then press Verify.</li>
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
          <span>Project id<InfoHint text="The Google Cloud project the processors live in, as shown in the console." /></span>
          <input
            className="text-input"
            value={draftSettings.gcp.project_id}
            placeholder="my-project-123456"
            onChange={(event) => setGcp({ project_id: event.target.value })}
          />
        </label>
        <label>
          <span>Region<InfoHint text="The processor's location, shown next to it in the console: eu, us, or another region. It is part of the endpoint, so a wrong one fails with a 404." /></span>
          <input
            className="text-input"
            value={draftSettings.gcp.location}
            placeholder="eu"
            onChange={(event) => setGcp({ location: event.target.value.trim() })}
          />
        </label>
        <label>
          <span>OCR processor id<InfoHint text="The id of a Document OCR processor, from the processor's detail page. Not its display name." /></span>
          <input
            className="text-input"
            value={draftSettings.gcp.ocr_processor_id}
            placeholder="262c0e092e95a1d"
            onChange={(event) => setGcp({ ocr_processor_id: event.target.value.trim() })}
          />
        </label>
        <label>
          <span>Layout Parser processor id<InfoHint text="The id of a Layout Parser processor. It reads the same page but keeps headings, tables and lists." /></span>
          <input
            className="text-input"
            value={draftSettings.gcp.layout_processor_id}
            placeholder="7638d53e4d6176f0"
            onChange={(event) => setGcp({ layout_processor_id: event.target.value.trim() })}
          />
        </label>
      </div>

      <div className="key-row">
        <button
          className="secondary-button"
          disabled={verifying}
          onClick={() => {
            setVerifying(true);
            void api
              .verifyGcpKey()
              .then(setStatus)
              .catch(() => undefined)
              .finally(() => setVerifying(false));
          }}
        >
          {verifying ? <LoaderCircle className="spin" size={14} /> : <ShieldCheck size={14} />} Verify connection
        </button>
        <p className="field-help">
          Sends one blank page to each configured processor, using the settings already saved.
          That is a real call, so it costs one page each.
        </p>
      </div>

      {verified.length > 0 && (
        <p className="field-help good-note">
          <Check size={12} /> Answered: {verified.map((id) => <code key={id}>{id}</code>).reduce((all, item) => <>{all}, {item}</>)}
        </p>
      )}
      {status?.configured && status.problem && (
        <div className="alert error-alert" role="status">
          <AlertCircle size={17} />
          <span>{status.problem}</span>
        </div>
      )}

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
      </div>
      <p className="field-help">
        Rates you can edit, noted on {draftSettings.gcp.pricing_checked_on}. They are not read from
        Google. A run records the pages it sent; the cost shown in Lab is worked out from these.
      </p>
    </div>
  );
}
