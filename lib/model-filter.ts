/** Narrowing a long model list down to the ones worth looking at. */

import type { ModelInfo } from "./types";

export type RunsFilter = "any" | "local" | "api";
export type VisionFilter = "any" | "vision" | "text";
export type SizeFilter = "any" | "small" | "medium" | "large";

export type ModelFilters = {
  runs?: RunsFilter;
  vision?: VisionFilter;
  size?: SizeFilter;
};

const GB = 1024 ** 3;

export const sizeBuckets: { value: SizeFilter; label: string; max: number }[] = [
  { value: "any", label: "Any size", max: Infinity },
  { value: "small", label: "Under 4 GB", max: 4 * GB },
  { value: "medium", label: "4 – 12 GB", max: 12 * GB },
  { value: "large", label: "Over 12 GB", max: Infinity },
];

function matchesSize(model: ModelInfo, size: SizeFilter): boolean {
  if (size === "any") return true;
  // A hosted model occupies nothing here, so no size bucket can claim it.
  if (!model.size_bytes) return false;
  if (size === "small") return model.size_bytes < 4 * GB;
  if (size === "medium") return model.size_bytes >= 4 * GB && model.size_bytes <= 12 * GB;
  return model.size_bytes > 12 * GB;
}

export function filterModels(models: ModelInfo[], filters: ModelFilters): ModelInfo[] {
  const { runs = "any", vision = "any", size = "any" } = filters;
  return models.filter((model) => {
    const isLocal = model.provider !== "gemini";
    if (runs === "local" && !isLocal) return false;
    if (runs === "api" && isLocal) return false;
    if (vision === "vision" && !model.vision) return false;
    if (vision === "text" && model.vision) return false;
    return matchesSize(model, size);
  });
}
