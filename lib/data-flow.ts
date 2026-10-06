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
  // True when every Document AI step reads only a PDF without text; see
  // uploadsOnlyScans. Kinds alone cannot say so.
  onlyScansUploaded = false,
): DataFlow {
  const uploaded = readsInTheCloud(steps);
  const callsModel = usesModel(steps);
  // A hosted model that is never called sends nothing.
  const modelInTheCloud = (provider === "gemini" || provider === "model_garden") && callsModel;
  // A self-hosted model answers on the server this deployment runs it on.
  const modelOnServer = provider === "model_server" && callsModel;

  if (!uploaded && !modelInTheCloud && !modelOnServer) {
    return {
      heading: "Private processing",
      detail: "Documents stay on this machine: every step runs here.",
      leavesTheMachine: false,
    };
  }

  const destinations: string[] = [];
  if (uploaded) {
    destinations.push(onlyScansUploaded
      ? "Google Document AI reads the pages of any PDF that carries no text of its own"
      : "Google Document AI reads the pages");
  }
  if (modelInTheCloud) destinations.push(provider === "model_garden" ? "Google Model Garden sends the document to the selected partner model to extract the fields" : "the Gemini API extracts the fields");
  if (modelOnServer) destinations.push("the model server configured for this deployment extracts the fields");

  const closing = !callsModel
    ? "No language model is involved."
    : modelInTheCloud || modelOnServer
      ? "Nothing is kept on this machine by them."
      : "The model answers on this machine.";

  return {
    heading: uploaded || modelInTheCloud ? (modelOnServer ? "Sent to Google and the model server" : "Sent to Google") : "Sent to the model server",
    detail: `${destinations.join(", and ")}. ${closing}`,
    leavesTheMachine: true,
  };
}
