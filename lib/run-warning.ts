/**
 * What is worth saying before a run that is about to take a very long time.
 *
 * A statement of what the configuration implies, not a recommendation: how
 * long is too long is the reader's call, and a slow run on a test bench is a
 * perfectly reasonable thing to start.
 */

import type { ModelInfo } from "./types";

const RENDERS_IMAGES = "render_pages";

export function runWarning(model: ModelInfo | undefined, steps: string[]): string | null {
  if (!model || model.provider === "gemini") return null;
  if (!model.requires_safe_profile) return null;
  if (!steps.includes(RENDERS_IMAGES)) return null;

  return (
    `${model.name} runs on the processor here, and this pipeline sends it one full page ` +
    `image per document. Both the load and each document take minutes rather than seconds.`
  );
}
