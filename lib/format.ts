import type { EntityFormat, ModelInfo, ModelRuntimeState } from "./types";
import type { LabelMode } from "./labels";

export const formatLabels: Record<EntityFormat, string> = {
  text: "Text",
  date: "Date · YYYY-MM-DD",
  currency: "Currency · ISO 4217",
  decimal: "Decimal number",
  integer: "Integer number",
};

export const labelModes: Record<LabelMode, string> = {
  skip: "Not labelled",
  value: "Value",
  absent: "Absent in document",
};

export function percent(accuracy: number | null | undefined): string {
  return accuracy === null || accuracy === undefined ? "—" : `${Math.round(accuracy * 100)}%`;
}

/** Bands for colouring a score. Deliberately blunt: good, fair, poor. */
export function accuracyClass(accuracy: number | null | undefined): string {
  if (accuracy === null || accuracy === undefined) return "";
  if (accuracy >= 0.9) return "good";
  if (accuracy >= 0.6) return "fair";
  return "poor";
}

export function seconds(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? "—" : `${(ms / 1000).toFixed(1)} s`;
}

export function describeValue(value: unknown): string {
  return value === null || value === undefined ? "—" : String(value);
}

/** Sizes as people read them on a model card or a spec sheet. */
export function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export const modelStateLabels: Record<ModelRuntimeState, string> = {
  not_loaded: "Model not loaded",
  loaded: "Model in memory",
  loading: "Loading model",
  warming_up: "Warming up",
  ready: "Model ready",
  error: "Model error",
  profile_mismatch: "Needs reload",
};

/**
 * The model to show, given what this machine actually has installed.
 *
 * Three cases, and they are genuinely different: a model that is here, a model
 * named in settings that is not (a settings file can arrive from another
 * machine), and no choice made at all, which is how a fresh install starts.
 */
export function modelDisplayName(
  modelId: string,
  models: Pick<ModelInfo, "id" | "name">[],
): string {
  if (!modelId.trim()) return "No model selected";
  return models.find((model) => model.id === modelId)?.name ?? modelId;
}

export function modelStatusLabel(
  modelId: string,
  model: Pick<ModelInfo, "runtime_state"> | undefined,
): string {
  if (model) return modelStateLabels[model.runtime_state];
  // Having chosen nothing is not the same as having chosen something missing.
  return modelId.trim() ? "Model unavailable" : "Choose a model in LLM";
}
