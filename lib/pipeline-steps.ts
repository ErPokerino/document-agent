/**
 * What a pipeline does, read from its step kinds alone.
 *
 * Both questions here were assumed rather than asked, and both assumptions were
 * wrong for the same pipeline. A Custom Extractor pipeline was made to wait for
 * a language model it never calls, and was described as private processing
 * while it uploaded every page to Google.
 */

import type { PipelineStep, StepKind } from "./types";

// Written as sets of StepKind so that renaming a step in the backend fails the
// type check here rather than quietly making one of these questions answer
// "no" forever. The functions still take plain strings, because what a running
// backend reports is not this file's to assume.

/** Steps that send the pages to Google. */
const CLOUD_READERS: ReadonlySet<string> = new Set<StepKind>([
  "document_ai_ocr",
  "document_ai_layout",
  "document_ai_extract",
]);

/** Steps that can call the selected language model. */
const MODEL_CALLERS: ReadonlySet<string> = new Set<StepKind>(["llm_extract", "supplier_rules"]);

export function readsInTheCloud(kinds: string[]): boolean {
  return kinds.some((kind) => CLOUD_READERS.has(kind));
}

/** The OCR step setting that mirrors OCR_ONLY_WITHOUT_PDF_TEXT in the backend. */
export const OCR_ONLY_WITHOUT_PDF_TEXT = "only_without_pdf_text";

/** An OCR step that reads only a document Read PDF text found no text on. */
export function isPdfTextFallback(step: Pick<PipelineStep, "kind" | "config">): boolean {
  return step.kind === "document_ai_ocr" && step.config[OCR_ONLY_WITHOUT_PDF_TEXT] === true;
}

/**
 * Whether the only pages that go to Google are those of a PDF without text.
 *
 * Such a pipeline still uploads — a scan in the batch is enough — so it is
 * never private processing; it is a narrower claim about which documents go.
 */
export function uploadsOnlyScans(steps: Pick<PipelineStep, "kind" | "config">[]): boolean {
  const readers = steps.filter((step) => CLOUD_READERS.has(step.kind));
  return readers.length > 0 && readers.every(isPdfTextFallback);
}

/**
 * Supplier rules count: one of them may be an instruction to ask the model
 * again, and which supplier a document is from is not known until the run is
 * under way.
 */
export function usesModel(kinds: string[]): boolean {
  return kinds.some((kind) => MODEL_CALLERS.has(kind));
}
