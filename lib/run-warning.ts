/**
 * What is worth saying before a run that is about to take a very long time.
 *
 * Not a block: it is a legitimate thing to try, and the only way to know the
 * real number is to measure. But a model kept off the GPU and handed page
 * images is minutes per document here, and that is better known before a run
 * than after twenty of them.
 */

import type { ModelInfo } from "./types";

const RENDERS_IMAGES = "render_pages";

export function runWarning(model: ModelInfo | undefined, steps: string[]): string | null {
  if (!model || model.provider === "gemini") return null;
  if (!model.requires_safe_profile) return null;
  if (!steps.includes(RENDERS_IMAGES)) return null;

  return (
    `${model.name} is too large for this machine's GPU, so it runs on the processor, and ` +
    `this pipeline sends it a full page image per document. Expect minutes per document, ` +
    `and a runtime that may give up part way. A pipeline that reads the page with OCR or ` +
    `the Layout Parser sends this model text instead, which is far quicker.`
  );
}
