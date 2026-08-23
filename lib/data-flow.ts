/**
 * Where a document actually goes, given the model and the pipeline.
 *
 * This used to read the provider alone and say "processed exclusively by the
 * local model" — which was false for every pipeline with a Document AI step,
 * because the page is uploaded to Google whatever answers afterwards. A wrong
 * claim about where documents go is the worst copy in the app to get wrong.
 */

import type { AppSettings } from "./types";

const CLOUD_READERS = new Set(["document_ai_ocr", "document_ai_layout"]);

export type DataFlow = {
  heading: string;
  detail: string;
  leavesTheMachine: boolean;
};

export function describeDataFlow(
  provider: AppSettings["provider"],
  steps: string[],
): DataFlow {
  const readsInTheCloud = steps.some((step) => CLOUD_READERS.has(step));
  const modelInTheCloud = provider === "gemini";

  if (!readsInTheCloud && !modelInTheCloud) {
    return {
      heading: "Private processing",
      detail: "Documents stay on this machine: every step runs here.",
      leavesTheMachine: false,
    };
  }

  const destinations: string[] = [];
  if (readsInTheCloud) destinations.push("Google Document AI reads the pages");
  if (modelInTheCloud) destinations.push("the Gemini API extracts the fields");

  return {
    heading: "Sent to Google",
    detail:
      `${destinations.join(", and ")}. ` +
      (modelInTheCloud
        ? "Nothing is kept on this machine by them."
        : "The model answers on this machine."),
    leavesTheMachine: true,
  };
}
