import type { AppSettings, GeminiKeyStatus, HostedModelCheck, HostedRate, ModelInfo, PublishedRate } from "./types";

/** Who makes a hosted model. Each has one card in LLM, laid out the same way. */
export type Publisher = "google" | "anthropic" | "xai";
export type HostedLocation = "eu" | "us" | "global";

export const publishers: { id: Publisher; family: string; company: string; title: string }[] = [
  { id: "google", family: "Gemini", company: "Google", title: "Google Gemini" },
  { id: "anthropic", family: "Claude", company: "Anthropic", title: "Anthropic Claude" },
  { id: "xai", family: "Grok", company: "xAI", title: "xAI Grok" },
];

// Where each publisher's models can be asked on Vertex AI. Grok has no EU
// endpoint; a single model may be offered in fewer places (Verify says).
export const publisherLocations: Record<Publisher, HostedLocation[]> = {
  google: ["eu", "us", "global"],
  anthropic: ["eu", "us", "global"],
  xai: ["us", "global"],
};

export const locationLabels: Record<string, string> = { eu: "EU", us: "US", global: "Global" };

export function locationLabel(location: string | null | undefined): string {
  return location ? locationLabels[location] ?? location : "";
}

export function publisherOf(model: Pick<ModelInfo, "provider" | "publisher">): Publisher | null {
  if (model.publisher === "google" || model.publisher === "anthropic" || model.publisher === "xai") return model.publisher;
  return model.provider === "gemini" ? "google" : null;
}

/** The location on screen, saved or not: what a run would use once saved. */
export function draftLocation(
  settings: AppSettings,
  publisher: Publisher,
  keyStatus: GeminiKeyStatus | null,
): string | null {
  if (publisher === "anthropic") return settings.model_garden.claude_location;
  if (publisher === "xai") return settings.model_garden.grok_location;
  if (keyStatus?.access !== "vertex") return null;
  return settings.gemini.location ?? keyStatus.deployment_location ?? keyStatus.vertex_location;
}

// What each publisher's models accept as reasoning effort. Gemini calls it a
// thinking level; Claude and Grok call it effort. The control is the same.
export const effortLevels: Record<Publisher, string[]> = {
  google: ["low", "medium", "high"],
  anthropic: ["low", "medium", "high", "xhigh", "max"],
  xai: ["low", "medium", "high"],
};
export const effortLabels: Record<string, string> = { low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max" };

// Grok's limit is bounded by its output quota, which every request reserves.
export const outputLimits: Record<Publisher, { min: number; max: number }> = {
  google: { min: 256, max: 32000 },
  anthropic: { min: 256, max: 32000 },
  xai: { min: 256, max: 10000 },
};

export type HostedControls = { location: string | null; effort: string; maxOutputTokens: number };

export function controlsOf(settings: AppSettings, publisher: Publisher, keyStatus: GeminiKeyStatus | null): HostedControls {
  const garden = settings.model_garden;
  if (publisher === "anthropic") return { location: garden.claude_location, effort: garden.claude_effort, maxOutputTokens: garden.claude_max_output_tokens };
  if (publisher === "xai") return { location: garden.grok_location, effort: garden.grok_effort, maxOutputTokens: garden.grok_max_output_tokens };
  return { location: draftLocation(settings, "google", keyStatus), effort: settings.gemini.thinking_level, maxOutputTokens: settings.gemini.max_output_tokens };
}

export function withControls(settings: AppSettings, publisher: Publisher, change: Partial<HostedControls>): AppSettings {
  const garden = settings.model_garden;
  if (publisher === "google") {
    return { ...settings, gemini: {
      ...settings.gemini,
      ...(change.location !== undefined && { location: change.location as AppSettings["gemini"]["location"] }),
      ...(change.effort !== undefined && { thinking_level: change.effort as AppSettings["gemini"]["thinking_level"] }),
      ...(change.maxOutputTokens !== undefined && { max_output_tokens: change.maxOutputTokens }),
    } };
  }
  const prefix = publisher === "anthropic" ? "claude" : "grok";
  return { ...settings, model_garden: {
    ...garden,
    ...(change.location !== undefined && { [`${prefix}_location`]: change.location }),
    ...(change.effort !== undefined && { [`${prefix}_effort`]: change.effort }),
    ...(change.maxOutputTokens !== undefined && { [`${prefix}_max_output_tokens`]: change.maxOutputTokens }),
  } };
}

export function checkFor(
  checks: HostedModelCheck[],
  model: string,
  location: string | null,
): HostedModelCheck | undefined {
  return location ? checks.find((check) => check.model === model && check.location === location) : undefined;
}

export const checkLabels: Record<HostedModelCheck["status"], string> = {
  answering: "Answering",
  no_quota: "Quota refused",
  not_offered: "Not offered",
  refused: "Refused",
};

/** How a request reaches the model. Every hosted model goes through Vertex AI, unless Gemini uses a key. */
export function routeLabel(model: Pick<ModelInfo, "provider">, keyStatus: GeminiKeyStatus | null): string {
  if (model.provider === "gemini" && keyStatus?.access !== "vertex") return "Gemini API";
  return "Vertex AI";
}

export const rateKey = (model: string, location: string) => `${model}@${location}`;

export type RateField = keyof HostedRate;

/** The rate a request would be costed at: the one edited in LLM, else Google's. */
export function effectiveRate(
  settings: AppSettings,
  published: PublishedRate[],
  model: string,
  location: string,
): { rate: HostedRate; edited: boolean; google: PublishedRate | undefined } {
  const google = published.find((item) => item.model === model && item.location === location);
  const edited = settings.hosted_rates[rateKey(model, location)];
  const rate = edited ?? {
    input_per_million: google?.input_per_million ?? null,
    output_per_million: google?.output_per_million ?? null,
    cache_read_per_million: google?.cache_read_per_million ?? null,
  };
  return { rate, edited: edited !== undefined, google };
}

export function withRate(settings: AppSettings, key: string, rate: HostedRate | null): AppSettings {
  const rates = { ...settings.hosted_rates };
  if (rate === null) delete rates[key];
  else rates[key] = rate;
  return { ...settings, hosted_rates: rates };
}
