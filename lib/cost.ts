import type { ModelPricing } from "./types";

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

export function formatUsd(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1) return `$${value.toFixed(2)}`;
  // Two significant figures, so a sub-cent amount is still legible.
  return `$${value.toPrecision(2)}`;
}
