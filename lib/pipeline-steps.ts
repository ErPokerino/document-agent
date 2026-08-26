/**
 * What a pipeline does, read from its step kinds alone.
 *
 * Both questions here were assumed rather than asked, and both assumptions were
 * wrong for the same pipeline. A Custom Extractor pipeline was made to wait for
 * a language model it never calls, and was described as private processing
 * while it uploaded every page to Google.
 */

/** Steps that send the pages to Google. */
const CLOUD_READERS = new Set(["document_ai_ocr", "document_ai_layout", "document_ai_extract"]);

/** Steps that can call the selected language model. */
const MODEL_CALLERS = new Set(["llm_extract", "supplier_rules"]);

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
