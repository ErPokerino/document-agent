/**
 * Where a document actually goes, given the model and the pipeline.
 *
 * This used to read the provider alone and say "processed exclusively by the
 * local model" — which was false for every pipeline with a Document AI step,
 * because the page is uploaded to Google whatever answers afterwards. A wrong
 * claim about where documents go is the worst copy in the app to get wrong.
 */

import { readsInTheCloud, usesModel } from "./pipeline-steps.ts";
import type { AppSettings } from "./types";

export type DataFlow = {
  heading: string;
  detail: string;
  leavesTheMachine: boolean;
};

export function describeDataFlow(
  provider: AppSettings["provider"],
  steps: string[],
): DataFlow {
  const uploaded = readsInTheCloud(steps);
  const callsModel = usesModel(steps);
  // A hosted model that is never called sends nothing.
  const modelInTheCloud = provider === "gemini" && callsModel;

  if (!uploaded && !modelInTheCloud) {
    return {
      heading: "Private processing",
      detail: "Documents stay on this machine: every step runs here.",
      leavesTheMachine: false,
    };
  }

  const destinations: string[] = [];
  if (uploaded) destinations.push("Google Document AI reads the pages");
  if (modelInTheCloud) destinations.push("the Gemini API extracts the fields");

  const closing = !callsModel
    ? "No language model is involved."
    : modelInTheCloud
      ? "Nothing is kept on this machine by them."
      : "The model answers on this machine.";

  return {
    heading: "Sent to Google",
    detail: `${destinations.join(", and ")}. ${closing}`,
    leavesTheMachine: true,
  };
}
