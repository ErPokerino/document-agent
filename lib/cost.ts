import type { GcpSettings, ModelPricing } from "./types";

/**
 * Cost derived from token counts and a configured rate.
 *
 * Deliberately not stored on a run. Token counts are facts and never go stale;
 * a price is a setting with an expiry date, and Gemini 3.7 Flash is already
 * scheduled to double on 1 January 2027. Deriving here means editing a rate
 * carries the whole history with it.
 *
 * Returns null rather than 0 when there is nothing to compute from: a missing
 * price is not the same as free, and a local run has no token counts at all.
 */
export function estimateCost(
  promptTokens: number,
  completionTokens: number,
  pricing: ModelPricing | undefined | null,
): number | null {
  if (!pricing) return null;
  const { input_per_million: input, output_per_million: output } = pricing;
  if (input === null || input === undefined || output === null || output === undefined) return null;
  if (!promptTokens && !completionTokens) return null;
  return (promptTokens * input + completionTokens * output) / 1_000_000;
}

/**
 * Document AI is billed per page, not per token, so it needs its own sum.
 * Same rule as the token rates: a missing price is not the same as free.
 */
export function documentAiCost(
  ocrPages: number,
  layoutPages: number,
  gcp: Pick<GcpSettings, "ocr_per_thousand_pages" | "layout_per_thousand_pages"> | undefined | null,
): number | null {
  if (!gcp) return null;
  if (!ocrPages && !layoutPages) return null;
  const ocrRate = gcp.ocr_per_thousand_pages;
  const layoutRate = gcp.layout_per_thousand_pages;
  if (ocrPages && (ocrRate === null || ocrRate === undefined)) return null;
  if (layoutPages && (layoutRate === null || layoutRate === undefined)) return null;
  return (ocrPages * (ocrRate ?? 0) + layoutPages * (layoutRate ?? 0)) / 1000;
}

/** What a run cost in total: the model call plus every page a processor read. */
export function totalCost(
  usage: { promptTokens: number; completionTokens: number; ocrPages: number; layoutPages: number },
  pricing: ModelPricing | undefined | null,
  gcp: Pick<GcpSettings, "ocr_per_thousand_pages" | "layout_per_thousand_pages"> | undefined | null,
): number | null {
  const model = estimateCost(usage.promptTokens, usage.completionTokens, pricing);
  const pages = documentAiCost(usage.ocrPages, usage.layoutPages, gcp);
  if (model === null && pages === null) return null;
  return (model ?? 0) + (pages ?? 0);
}

export function formatUsd(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1) return `$${value.toFixed(2)}`;
  // Two significant figures, so a sub-cent amount is still legible.
  return `$${value.toPrecision(2)}`;
}
