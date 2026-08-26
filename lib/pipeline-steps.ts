/**
 * What a pipeline does, read from its step kinds alone.
 *
 * Both questions here were assumed rather than asked, and both assumptions were
 * wrong for the same pipeline. A Custom Extractor pipeline was made to wait for
 * a language model it never calls, and was described as private processing
 * while it uploaded every page to Google.
 */

import type { StepKind } from "./types";

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

/**
 * Supplier rules count: one of them may be an instruction to ask the model
 * again, and which supplier a document is from is not known until the run is
 * under way.
 */
export function usesModel(kinds: string[]): boolean {
  return kinds.some((kind) => MODEL_CALLERS.has(kind));
}
