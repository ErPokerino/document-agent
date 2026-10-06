"use client";

import { AlertCircle, Check, CircleDot, Cloud, KeyRound, LoaderCircle, ShieldCheck, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { api } from "../../lib/api";
import { withoutRate } from "../../lib/cost";
import {
  checkFor,
  checkLabels,
  draftLocation,
  locationLabel,
  publisherLocations,
  publisherOf,
  publishers,
  routeLabel,
  type HostedLocation,
  type Publisher,
} from "../../lib/hosted-providers";
import type { AppSettings, GeminiKeyStatus, HostedModelCheck, ModelInfo, PartnerTariff } from "../../lib/types";

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
  tariffs: PartnerTariff[];
};

/** The availability of one model where it would run, as a chip. */
export function CheckChip({ check }: { check: HostedModelCheck | undefined }) {
  if (!check) return <em>Not verified</em>;
  return <em className={`check-${check.status}`} title={check.detail || undefined}>{checkLabels[check.status]}</em>;
}

/** One card per publisher, each laid out the same way: access, controls, the models and what they answered, prices. */
function ProviderCard(props: {
  icon: ReactNode;
  title: string;
  description: string;
  badge: string;
  online: boolean;
  fields: ReactNode;
  access?: ReactNode;
  models: ModelInfo[];
  location: string | null;
  checks: HostedModelCheck[];
  verifyDisabled: boolean;
  verifying: boolean;
  onVerify: () => void;
  help: ReactNode;
  pricing: ReactNode;
}) {
  return (
    <div className="settings-card provider-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon">{props.icon}</span>
        <div><h3>{props.title}</h3><p>{props.description}</p></div>
        <span className={`connection-badge ${props.online ? "online" : ""}`}><CircleDot size={12} /> {props.badge}</span>
      </div>
      {props.access}
      <div className="provider-fields">{props.fields}</div>

      <div className="provider-models">
        <div className="provider-models-heading">
          <p className="input-label">Models{props.location ? ` in ${locationLabel(props.location)}` : ""}</p>
          <button className="secondary-button" disabled={props.verifyDisabled || props.verifying} onClick={props.onVerify}>
            {props.verifying ? <LoaderCircle className="spin" size={14} /> : <ShieldCheck size={14} />} Verify
          </button>
        </div>
        {props.models.map((model) => {
          const check = checkFor(props.checks, model.id, props.location);
          return (
            <div className="provider-model" key={model.id}>
              <span><strong>{model.name}</strong>{model.preview && <small> · Preview</small>}</span>
              <span className="model-specs"><CheckChip check={check} /></span>
              {check?.detail && <small className="provider-model-detail">{check.detail}</small>}
            </div>
          );
        })}
      </div>
      <div className="field-help">{props.help}</div>

      <p className="input-label prompt-label">Price per million tokens (USD)</p>
      {props.pricing}
    </div>
  );
}

function LocationField({ id, value, locations, defaultLocation, onChange }: {
  id: string;
  value: string;
  locations: HostedLocation[];
  defaultLocation?: string | null;
  onChange: (value: string) => void;
}) {
  return (
    <label className="provider-field" htmlFor={id}>
      <span>Location</span>
      <select id={id} className="text-input" value={value} onChange={(event) => onChange(event.target.value)}>
        {defaultLocation !== undefined && <option value="">Deployment default{defaultLocation ? ` (${locationLabel(defaultLocation)})` : ""}</option>}
        {locations.map((location) => <option key={location} value={location}>{locationLabel(location)}</option>)}
      </select>
    </label>
  );
}

function PartnerPricing({ models, location, tariffs }: { models: ModelInfo[]; location: string; tariffs: PartnerTariff[] }) {
  const rows = models.map((model) => ({ model, rate: tariffs.find((item) => item.model === model.id && item.location === location) }));
  const checkedOn = rows.find((row) => row.rate)?.rate?.checked_on;
  return (
    <>
      <div className="pricing-grid">
        {rows.map(({ model, rate }) => (
          <div className="pricing-row readonly" key={model.id}>
            <code>{model.id}</code>
            <label><span>Input</span><b>{rate?.input ?? "—"}</b></label>
            <label><span>Output</span><b>{rate?.output ?? "—"}</b></label>
            <label><span>Cache read</span><b>{rate?.cache_read ?? "—"}</b></label>
          </div>
        ))}
      </div>
      <p className="field-help">
        Google&apos;s <a href={PRICING_URL} target="_blank" rel="noreferrer">Model Garden rates</a>{checkedOn ? `, checked on ${checkedOn}` : ""}, for
        {" "}{locationLabel(location)} up to 200k tokens of context. Each request stores the rate it was costed at, so
        history keeps its price when the location or the rates change.
      </p>
    </>
  );
}

export function HostedProviderCards(props: CardsProps) {
  const { draftSettings, setDraftSettings, keyStatus, checks, tariffs } = props;
  const throughVertex = keyStatus?.access === "vertex";
  const garden = draftSettings.model_garden;
  const setGarden = (update: Partial<AppSettings["model_garden"]>) =>
    setDraftSettings({ ...draftSettings, model_garden: { ...garden, ...update } });
  const of = (publisher: Publisher) => props.models.filter((model) => publisherOf(model) === publisher);
  const gardenConfigured = props.models.some((model) => model.provider === "model_garden" && model.ready);

  const geminiModels = of("google");
  const hostedIds = new Set(geminiModels.map((model) => model.id));
  const unpricedHosted = geminiModels.filter((model) => !(model.id in draftSettings.gemini.pricing));
  const geminiLocation = draftLocation(draftSettings, "google", keyStatus);

  const cards: Record<Publisher, ReactNode> = {
    google: (
      <ProviderCard
        key="google"
        icon={throughVertex ? <Cloud size={18} /> : <KeyRound size={18} />}
        title="Google Gemini"
        description={throughVertex
          ? "Through Vertex AI in this deployment's Google Cloud project, as its own service account: no key, billed to the project."
          : "Through the Gemini API with a key from Google AI Studio. The key is stored on this machine and never sent back to the browser."}
        badge={throughVertex ? `Vertex AI · ${locationLabel(geminiLocation)}` : keyStatus?.configured ? `Key ${keyStatus.hint}` : "No key"}
        online={Boolean(keyStatus?.configured)}
        access={!throughVertex && (
          <>
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
          </>
        )}
        fields={(
          <>
            {throughVertex && (
              <LocationField
                id="gemini-location"
                value={draftSettings.gemini.location ?? ""}
                locations={publisherLocations.google}
                defaultLocation={keyStatus?.deployment_location ?? null}
                onChange={(value) => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, location: (value || null) as AppSettings["gemini"]["location"] } })}
              />
            )}
            <label className="provider-field" htmlFor="thinking-level">
              <span>Thinking level</span>
              <select
                id="thinking-level"
                className="text-input"
                value={draftSettings.gemini.thinking_level}
                onChange={(event) => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, thinking_level: event.target.value as AppSettings["gemini"]["thinking_level"] } })}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
          </>
        )}
        models={geminiModels}
        location={throughVertex ? geminiLocation : null}
        checks={checks}
        verifyDisabled={!keyStatus?.configured}
        verifying={props.verifyingPublisher === "google"}
        onVerify={() => props.onVerify("google")}
        help={(
          <>
            {!throughVertex && keyStatus && keyStatus.verified_models.length > 0 && (
              <span className="good-note"><Check size={12} /> The key can use: {keyStatus.verified_models.join(", ")}.</span>
            )}
            {throughVertex
              ? " Verify asks each model for one token in the location shown. Gemini 3.1 Pro Preview is offered in Global only. "
              : " Verify lists the models the key can use. "}
            Higher thinking levels can increase latency and output tokens; thinking is billed as output and ignored by models without it.
          </>
        )}
        pricing={(
          <>
            <div className="pricing-grid">
              {Object.keys(draftSettings.gemini.pricing).length === 0 && <p className="field-help">No rates: the cost of Gemini runs is not estimated.</p>}
              {Object.entries(draftSettings.gemini.pricing).map(([modelId, price]) => (
                <div className="pricing-row" key={modelId}>
                  <code title={hostedIds.has(modelId) ? undefined : "Not selectable any more; kept to cost the runs that used it"}>{modelId}{hostedIds.has(modelId) ? "" : " · retired"}</code>
                  <label>
                    <span>Input</span>
                    <input
                      type="number" step="0.01" min="0"
                      value={price.input_per_million ?? ""}
                      onChange={(event) => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, pricing: { ...draftSettings.gemini.pricing, [modelId]: { ...price, input_per_million: event.target.value === "" ? null : Number(event.target.value) } } } })}
                    />
                  </label>
                  <label>
                    <span>Output</span>
                    <input
                      type="number" step="0.01" min="0"
                      value={price.output_per_million ?? ""}
                      onChange={(event) => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, pricing: { ...draftSettings.gemini.pricing, [modelId]: { ...price, output_per_million: event.target.value === "" ? null : Number(event.target.value) } } } })}
                    />
                  </label>
                  <button
                    className="icon-button"
                    title={`Remove the rate for ${modelId}`}
                    aria-label={`Remove the rate for ${modelId}`}
                    onClick={() => setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, pricing: withoutRate(draftSettings.gemini.pricing, modelId) } })}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}
              {unpricedHosted.length > 0 && (
                <label className="pricing-add">
                  <span>Add a rate for</span>
                  <select
                    value=""
                    onChange={(event) => {
                      if (!event.target.value) return;
                      setDraftSettings({ ...draftSettings, gemini: { ...draftSettings.gemini, pricing: { ...draftSettings.gemini.pricing, [event.target.value]: { input_per_million: null, output_per_million: null } } } });
                    }}
                  >
                    <option value="">Choose a Gemini model…</option>
                    {unpricedHosted.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}
                  </select>
                </label>
              )}
            </div>
            <p className="field-help">
              Rates you can edit, checked on {draftSettings.gemini.pricing_checked_on}. They are not read from Google:
              published prices change, and Gemini 3.8 Flash is already scheduled to double on 1 January 2027.
              Gemini 3.1 Pro Preview has context-dependent prices, so it has no flat estimate until a rate is set here.
            </p>
          </>
        )}
      />
    ),
    anthropic: (
      <ProviderCard
        key="anthropic"
        icon={<Cloud size={18} />}
        title="Anthropic Claude"
        description="Through Model Garden in this deployment's Google Cloud project, as its own service account: no Anthropic key, billed to the project."
        badge={gardenConfigured ? `Model Garden · ${locationLabel(garden.claude_location)}` : "Not configured"}
        online={gardenConfigured}
        fields={(
          <>
            <LocationField id="claude-location" value={garden.claude_location} locations={publisherLocations.anthropic}
              onChange={(value) => setGarden({ claude_location: value as AppSettings["model_garden"]["claude_location"] })} />
            <label className="provider-field" htmlFor="claude-effort">
              <span>Effort</span>
              <select id="claude-effort" className="text-input" value={garden.effort} onChange={(event) => setGarden({ effort: event.target.value as AppSettings["model_garden"]["effort"] })}>
                {(["low", "medium", "high", "xhigh", "max"] as const).map((value) => <option key={value} value={value}>{value === "xhigh" ? "Extra high" : value[0].toUpperCase() + value.slice(1)}</option>)}
              </select>
            </label>
            <label className="provider-field" htmlFor="claude-output">
              <span>Maximum output tokens</span>
              <input id="claude-output" className="text-input" type="number" min={256} max={10000} value={garden.claude_max_output_tokens}
                onChange={(event) => setGarden({ claude_max_output_tokens: Number(event.target.value) })} />
            </label>
          </>
        )}
        models={of("anthropic")}
        location={garden.claude_location}
        checks={checks}
        verifyDisabled={!gardenConfigured}
        verifying={props.verifyingPublisher === "anthropic"}
        onVerify={() => props.onVerify("anthropic")}
        help={<>Claude thinks adaptively; effort bounds how much, and thinking counts toward the output limit and the output charge. Verify asks each model for one token in the location shown: a model with no quota in this project answers 429 there, as it would in a run. Model Garden quota is granted per project, model and location.</>}
        pricing={<PartnerPricing models={of("anthropic")} location={garden.claude_location} tariffs={tariffs} />}
      />
    ),
    xai: (
      <ProviderCard
        key="xai"
        icon={<Cloud size={18} />}
        title="xAI Grok"
        description="Through Model Garden in this deployment's Google Cloud project, as its own service account: no xAI key, billed to the project."
        badge={gardenConfigured ? `Model Garden · ${locationLabel(garden.grok_location)}` : "Not configured"}
        online={gardenConfigured}
        fields={(
          <>
            <LocationField id="grok-location" value={garden.grok_location} locations={publisherLocations.xai}
              onChange={(value) => setGarden({ grok_location: value as AppSettings["model_garden"]["grok_location"] })} />
            <label className="provider-field" htmlFor="grok-output">
              <span>Maximum output tokens</span>
              <input id="grok-output" className="text-input" type="number" min={256} max={10000} value={garden.grok_max_output_tokens}
                onChange={(event) => setGarden({ grok_max_output_tokens: Number(event.target.value) })} />
            </label>
          </>
        )}
        models={of("xai")}
        location={garden.grok_location}
        checks={checks}
        verifyDisabled={!gardenConfigured}
        verifying={props.verifyingPublisher === "xai"}
        onVerify={() => props.onVerify("xai")}
        help={<>Grok reasons on every request and has no effort control; reasoning is billed as output. It has no EU endpoint. Its request and token quotas are shared by Workspace and Lab, so a run may wait for them.</>}
        pricing={<PartnerPricing models={of("xai")} location={garden.grok_location} tariffs={tariffs} />}
      />
    ),
  };

  return (
    <>
      <div className="provider-section-heading">
        <h3>Hosted providers</h3>
        <p>How each publisher&apos;s models are reached, and what a request costs. A location applies to every model of that publisher, and a run never moves to another location on its own.</p>
      </div>
      {publishers.map((publisher) => cards[publisher.id])}
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
  const family = publishers.find((item) => item.id === publisher)?.family;
  const location = draftLocation(settings, publisher, keyStatus);
  const check = checkFor(checks, model.id, location);
  const route = routeLabel(model, keyStatus);
  const where = location ? ` in ${locationLabel(location)}` : "";
  const usable = model.provider === "gemini" ? Boolean(keyStatus?.configured) : model.ready;
  const failed = check && check.status !== "answering";
  const title = !usable
    ? model.provider === "gemini" ? "An API key is required" : "No Google Cloud project is configured for Model Garden"
    : check?.status === "answering" ? `Answering through ${route}${where}`
    : failed ? `${checkLabels[check.status]}${where}`
    : `Reached through ${route}${where}`;
  const body = failed
    ? check.detail
    : !usable
      ? model.provider === "gemini" ? "Add the key in the Gemini settings below." : "This deployment names no project for partner models."
      : `Nothing is loaded for a hosted model. ${check ? "" : "Verify asks it for one token, so a refusal shows here instead of inside a run. "}Its settings are in the ${family} card below.`;
  return (
    <div className={`model-loader hosted ${failed ? "error" : "ready"}`}>
      <span className="model-loader-icon">{failed ? <AlertCircle size={17} /> : <Cloud size={17} />}</span>
      <div className="model-loader-copy">
        <strong>{title}</strong>
        <span>{body}</span>
      </div>
      <button className="model-load-button" disabled={!usable || verifying} onClick={onVerify}>
        {verifying ? <><LoaderCircle className="spin" size={14} /> Verifying…</> : <><ShieldCheck size={14} /> Verify</>}
      </button>
    </div>
  );
}
