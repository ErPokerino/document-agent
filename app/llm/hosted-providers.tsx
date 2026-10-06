"use client";

import { AlertCircle, Check, ChevronDown, CircleDot, Cloud, LoaderCircle, RotateCcw, ShieldCheck, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { api } from "../../lib/api";
import {
  checkFor,
  checkLabels,
  controlsOf,
  draftLocation,
  effectiveRate,
  effortLabels,
  effortLevels,
  locationLabel,
  outputLimits,
  publisherLocations,
  publisherOf,
  publishers,
  rateKey,
  routeLabel,
  withControls,
  withRate,
  type Publisher,
  type RateField,
} from "../../lib/hosted-providers";
import type { AppSettings, GeminiKeyStatus, HostedModelCheck, ModelInfo, PublishedRate } from "../../lib/types";

const PRICING_URL = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing";

type CardsProps = {
  models: ModelInfo[];
  draftSettings: AppSettings;
  setDraftSettings: (settings: AppSettings) => void;
  keyStatus: GeminiKeyStatus | null;
  setKeyStatus: (status: GeminiKeyStatus | null) => void;
  geminiKey: string;
  setGeminiKey: (key: string) => void;
  setSettingsError: (message: string | null) => void;
  checks: HostedModelCheck[];
  verifyingPublisher: Publisher | null;
  onVerify: (publisher: Publisher) => void;
  published: PublishedRate[];
  // The card of the selected model's publisher starts open.
  selectedPublisher: Publisher | null;
};

/** The availability of one model where it would run, as a chip. */
export function CheckChip({ check }: { check: HostedModelCheck | undefined }) {
  if (!check) return <em>Not verified</em>;
  return <em className={`check-${check.status}`} title={check.detail || undefined}>{checkLabels[check.status]}</em>;
}

const rateColumns: { field: RateField; label: string }[] = [
  { field: "input_per_million", label: "Input" },
  { field: "output_per_million", label: "Output" },
  { field: "cache_read_per_million", label: "Cache read" },
];

/** One table for every publisher: the rate each model is costed at where it runs, editable. */
function RatesTable({ models, location, settings, setSettings, published }: {
  models: ModelInfo[];
  location: string;
  settings: AppSettings;
  setSettings: (settings: AppSettings) => void;
  published: PublishedRate[];
}) {
  const checkedOn = published.find((item) => item.location === location)?.checked_on;
  return (
    <>
      <div className="pricing-grid">
        {models.map((model) => {
          const offered = published.some((item) => item.model === model.id && item.location === location);
          const { rate, edited, google } = effectiveRate(settings, published, model.id, location);
          const key = rateKey(model.id, location);
          return (
            <div className="pricing-row hosted-rate" key={model.id}>
              <span className="hosted-rate-model">
                <code>{model.id}</code>
                {offered && google?.scheduled && <small>Google from {google.scheduled}</small>}
              </span>
              {offered ? rateColumns.map(({ field, label }) => (
                <label key={field}>
                  <span>{label}</span>
                  <input
                    type="number" step="0.001" min="0"
                    aria-label={`${label} rate for ${model.id} in ${locationLabel(location)}`}
                    value={rate[field] ?? ""}
                    onChange={(event) => setSettings(withRate(settings, key, { ...rate, [field]: event.target.value === "" ? null : Number(event.target.value) }))}
                  />
                </label>
              )) : <span className="hosted-rate-absent">Not offered in {locationLabel(location)}</span>}
              {offered && (edited ? (
                <button className="icon-button" title="Use Google's published rate" aria-label={`Use Google's rate for ${model.id}`}
                  onClick={() => setSettings(withRate(settings, key, null))}>
                  <RotateCcw size={13} />
                </button>
              ) : <span className="hosted-rate-source" title="Google's published rate">Google</span>)}
            </div>
          );
        })}
      </div>
      <p className="field-help">
        USD per million tokens in {locationLabel(location)}, starting from <a href={PRICING_URL} target="_blank" rel="noreferrer">Google&apos;s published rates</a>
        {checkedOn ? ` (checked on ${checkedOn})` : ""}; an announced change applies from its date unless the rate is edited.
        An edited rate costs the requests made after saving, and each request keeps the rate it was costed at.
        An empty rate leaves the cost unknown. Above 200k tokens of context Google&apos;s long-context rates apply.
      </p>
    </>
  );
}

/** One card per publisher, the same parts in the same order: access, controls, models, rates. Collapsible. */
function ProviderCard(props: {
  publisher: Publisher;
  models: ModelInfo[];
  settings: AppSettings;
  setSettings: (settings: AppSettings) => void;
  keyStatus: GeminiKeyStatus | null;
  checks: HostedModelCheck[];
  published: PublishedRate[];
  configured: boolean;
  verifying: boolean;
  onVerify: () => void;
  access?: ReactNode;
  help: ReactNode;
  initiallyOpen: boolean;
}) {
  const [open, setOpen] = useState(props.initiallyOpen);
  // Choosing a model of this publisher opens its settings; nothing closes them but the person.
  const [selected, setSelected] = useState(props.initiallyOpen);
  if (selected !== props.initiallyOpen) {
    setSelected(props.initiallyOpen);
    if (props.initiallyOpen) setOpen(true);
  }
  const meta = publishers.find((item) => item.id === props.publisher)!;
  const throughKey = props.publisher === "google" && props.keyStatus?.access !== "vertex";
  const controls = controlsOf(props.settings, props.publisher, props.keyStatus);
  const location = controls.location;
  const limits = outputLimits[props.publisher];
  const route = throughKey ? "Gemini API" : "Vertex AI";
  const badge = !props.configured ? (throughKey ? "No key" : "Not configured") : `${route}${location ? ` · ${locationLabel(location)}` : ""}`;
  const summary = [
    location ? locationLabel(location) : route,
    `Reasoning ${effortLabels[controls.effort]?.toLowerCase() ?? controls.effort}`,
    `Up to ${controls.maxOutputTokens.toLocaleString()} output tokens`,
  ].join(" · ");
  const id = `provider-${props.publisher}`;
  return (
    <div className={`settings-card provider-card ${open ? "open" : ""}`}>
      <button className="provider-card-toggle" aria-expanded={open} aria-controls={`${id}-body`} onClick={() => setOpen(!open)}>
        <span className="settings-card-icon"><Cloud size={18} /></span>
        <span className="provider-card-title">
          <strong>{meta.title}</strong>
          <small>{open
            ? throughKey
              ? "Through the Gemini API with a key from Google AI Studio, stored on this machine only."
              : `Through Vertex AI in this deployment's Google Cloud project, as its own service account: no API key, billed to the project.`
            : summary}</small>
        </span>
        <span className={`connection-badge ${props.configured ? "online" : ""}`}><CircleDot size={12} /> {badge}</span>
        <ChevronDown className="provider-card-chevron" size={16} />
      </button>

      <div id={`${id}-body`} className="provider-card-body" hidden={!open}>
        {props.access}
        <div className="provider-fields">
          <label className="provider-field" htmlFor={`${id}-location`}>
            <span>Location</span>
            <select id={`${id}-location`} className="text-input" disabled={throughKey} value={location ?? ""}
              onChange={(event) => props.setSettings(withControls(props.settings, props.publisher, { location: event.target.value }))}>
              {throughKey && <option value="">None with an API key</option>}
              {publisherLocations[props.publisher].map((value) => <option key={value} value={value}>{locationLabel(value)}</option>)}
            </select>
          </label>
          <label className="provider-field" htmlFor={`${id}-effort`}>
            <span>Reasoning effort</span>
            <select id={`${id}-effort`} className="text-input" value={controls.effort}
              onChange={(event) => props.setSettings(withControls(props.settings, props.publisher, { effort: event.target.value }))}>
              {effortLevels[props.publisher].map((value) => <option key={value} value={value}>{effortLabels[value]}</option>)}
            </select>
          </label>
          <label className="provider-field" htmlFor={`${id}-output`}>
            <span>Maximum output tokens</span>
            <input id={`${id}-output`} className="text-input" type="number" min={limits.min} max={limits.max} value={controls.maxOutputTokens}
              onChange={(event) => props.setSettings(withControls(props.settings, props.publisher, { maxOutputTokens: Number(event.target.value) }))} />
          </label>
        </div>
        <p className="field-help">{props.help}</p>

        <div className="provider-models">
          <div className="provider-models-heading">
            <p className="input-label">Models{location ? ` in ${locationLabel(location)}` : ""}</p>
            <button className="secondary-button" disabled={!props.configured || props.verifying} onClick={props.onVerify}>
              {props.verifying ? <LoaderCircle className="spin" size={14} /> : <ShieldCheck size={14} />} Verify
            </button>
          </div>
          {props.models.map((model) => {
            const check = checkFor(props.checks, model.id, location);
            return (
              <div className="provider-model" key={model.id}>
                <span><strong>{model.name}</strong>{model.preview && <small> · Preview</small>}</span>
                <span className="model-specs"><CheckChip check={check} /></span>
                {check?.detail && <small className="provider-model-detail">{check.detail}</small>}
              </div>
            );
          })}
        </div>

        <p className="input-label prompt-label">Price per million tokens (USD)</p>
        <RatesTable models={props.models} location={location ?? "global"} settings={props.settings} setSettings={props.setSettings} published={props.published} />
      </div>
    </div>
  );
}

export function HostedProviderCards(props: CardsProps) {
  const { draftSettings, setDraftSettings, keyStatus } = props;
  const throughVertex = keyStatus?.access === "vertex";
  const of = (publisher: Publisher) => props.models.filter((model) => publisherOf(model) === publisher);
  const gardenConfigured = props.models.some((model) => model.provider === "model_garden" && model.ready);
  const help: Record<Publisher, ReactNode> = {
    google: <>Gemini 3.1 Pro Preview is offered in Global only. Reasoning effort is Gemini&apos;s thinking level; Gemini 3.5 Flash Lite does not think and ignores it. Thinking counts toward the output limit and is billed as output.</>,
    anthropic: <>Claude thinks adaptively, and effort bounds how much. Thinking counts toward the output limit and is billed as output. Vertex AI grants Claude quota per project, model and location; without it every request is refused with 429.</>,
    xai: <>Grok reasons on every request, and effort sets how much. Reasoning counts toward the output limit and is billed as output. Grok has no EU endpoint, and its output limit is bounded by its token quota, which Workspace and Lab share.</>,
  };
  const access = !throughVertex && (
    <div className="provider-access">
      <label className="input-label" htmlFor="gemini-key">API key</label>
      <div className="key-row">
        <input
          id="gemini-key"
          className="text-input"
          type="password"
          autoComplete="off"
          placeholder={keyStatus?.configured ? "Leave empty to keep the stored key" : "Paste your Google AI Studio key"}
          value={props.geminiKey}
          onChange={(event) => props.setGeminiKey(event.target.value)}
        />
        {keyStatus?.configured && (
          <button
            className="secondary-button danger"
            onClick={() => {
              void api.clearGeminiKey()
                .then(() => api.geminiKeyStatus())
                .then(props.setKeyStatus)
                .catch((cause) => props.setSettingsError(cause instanceof Error ? cause.message : String(cause)));
              props.setGeminiKey("");
            }}
          >
            <Trash2 size={14} /> Remove
          </button>
        )}
      </div>
      <p className="field-help">Saving with the field empty keeps the key already stored. The key is written to backend/data/settings.json on this machine.</p>
      {keyStatus && keyStatus.verified_models.length > 0 && (
        <p className="field-help good-note"><Check size={12} /> The key can use: {keyStatus.verified_models.join(", ")}.</p>
      )}
    </div>
  );

  return (
    <>
      <div className="provider-section-heading">
        <h3>Hosted providers</h3>
        <p>Each publisher&apos;s models on Google Cloud: where they run, how much they reason, how long they may answer, and what a request costs. A location applies to every model of its publisher, and a run never moves to another location on its own.</p>
      </div>
      {publishers.map(({ id }) => (
        <ProviderCard
          key={id}
          publisher={id}
          models={of(id)}
          settings={draftSettings}
          setSettings={setDraftSettings}
          keyStatus={keyStatus}
          checks={props.checks}
          published={props.published}
          configured={id === "google" ? Boolean(keyStatus?.configured) : gardenConfigured}
          verifying={props.verifyingPublisher === id}
          onVerify={() => props.onVerify(id)}
          access={id === "google" ? access : undefined}
          help={help[id]}
          initiallyOpen={props.selectedPublisher === id}
        />
      ))}
    </>
  );
}

/** Where the selected hosted model stands, in the place a local model shows Load & warm up. */
export function HostedModelStatus({ model, settings, keyStatus, checks, verifying, onVerify }: {
  model: ModelInfo;
  settings: AppSettings;
  keyStatus: GeminiKeyStatus | null;
  checks: HostedModelCheck[];
  verifying: boolean;
  onVerify: () => void;
}) {
  const publisher = publisherOf(model);
  if (!publisher) return null;
  const title = publishers.find((item) => item.id === publisher)?.title;
  const location = draftLocation(settings, publisher, keyStatus);
  const check = checkFor(checks, model.id, location);
  const route = routeLabel(model, keyStatus);
  const where = location ? ` in ${locationLabel(location)}` : "";
  const usable = model.provider === "gemini" ? Boolean(keyStatus?.configured) : model.ready;
  const failed = check && check.status !== "answering";
  const heading = !usable
    ? model.provider === "gemini" ? "An API key is required" : "No Google Cloud project is configured"
    : check?.status === "answering" ? `Answering through ${route}${where}`
    : failed ? `${checkLabels[check.status]}${where}`
    : `Reached through ${route}${where}`;
  const body = failed
    ? check.detail
    : !usable
      ? model.provider === "gemini" ? "Add the key in the Google Gemini settings below." : "This deployment names no project for Vertex AI."
      : `Nothing is loaded for a hosted model. ${check ? "" : "Verify asks it for one token, so a refusal shows here instead of inside a run. "}Its settings are in the ${title} card below.`;
  return (
    <div className={`model-loader hosted ${failed ? "error" : "ready"}`}>
      <span className="model-loader-icon">{failed ? <AlertCircle size={17} /> : <Cloud size={17} />}</span>
      <div className="model-loader-copy">
        <strong>{heading}</strong>
        <span>{body}</span>
      </div>
      <button className="model-load-button" disabled={!usable || verifying} onClick={onVerify}>
        {verifying ? <><LoaderCircle className="spin" size={14} /> Verifying…</> : <><ShieldCheck size={14} /> Verify</>}
      </button>
    </div>
  );
}
