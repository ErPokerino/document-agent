import type { AppSettings, GeminiKeyStatus, HostedModelCheck, ModelInfo } from "./types";

/** Who makes a hosted model. Each has one card in LLM, laid out the same way. */
export type Publisher = "google" | "anthropic" | "xai";
export type HostedLocation = "eu" | "us" | "global";

export const publishers: { id: Publisher; family: string; company: string }[] = [
  { id: "google", family: "Gemini", company: "Google" },
  { id: "anthropic", family: "Claude", company: "Anthropic" },
  { id: "xai", family: "Grok", company: "xAI" },
];

// Where each publisher's models can be asked through Google Cloud. Grok has
// no EU endpoint; Gemini's choice applies through Vertex AI only.
export const publisherLocations: Record<Publisher, HostedLocation[]> = {
  google: ["eu", "us", "global"],
  anthropic: ["eu", "us", "global"],
  xai: ["global", "us"],
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

export function checkFor(
  checks: HostedModelCheck[],
  model: string,
  location: string | null,
): HostedModelCheck | undefined {
  return location ? checks.find((check) => check.model === model && check.location === location) : undefined;
}

export const checkLabels: Record<HostedModelCheck["status"], string> = {
  answering: "Answering",
  no_quota: "No quota",
  not_offered: "Not offered",
  refused: "Refused",
};

/** How a request reaches the model, as the provider tag and the card badge say it. */
export function routeLabel(model: Pick<ModelInfo, "provider">, keyStatus: GeminiKeyStatus | null): string {
  if (model.provider === "model_garden") return "Model Garden";
  return keyStatus?.access === "vertex" ? "Vertex AI" : "Gemini API";
}
