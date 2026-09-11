import type { Evaluation } from "./types";

export function versionLabel(version: string): string {
  return version.replace(/^pretrained-foundation-model-/, "Foundation ");
}

export function engineOptionLabel(run: Evaluation): string {
  return [engineLabel(run), run.extraction_engine?.version ? versionLabel(run.extraction_engine.version) : null,
    run.steps?.includes("document_ai_extract") && run.model !== "Not used" ? `LLM: ${run.model}` : null].filter(Boolean).join(" · ");
}

export function engineLabel(run: Pick<Evaluation, "model" | "steps" | "extraction_engine">): string {
  if (!run.steps?.includes("document_ai_extract")) return run.model;
  const extra = run.extraction_engine?.additional_processors?.length || 0;
  return (run.extraction_engine?.display_name || "Custom Extractor") + (extra ? ` +${extra} extractor${extra > 1 ? "s" : ""}` : "");
}

export function engineDetail(run: Pick<Evaluation, "model" | "steps" | "extraction_engine">): string {
  if (!run.steps?.includes("document_ai_extract")) return run.model;
  const engine = run.extraction_engine;
  return ["Document AI Custom Extractor", engine?.processor_id,
    engine?.version ? `Version: ${engine.version}` : "Version not recorded",
    engine?.base_model ? `Base model: ${engine.base_model}` : null,
    ...(engine?.additional_processors || []).map(other => `${other.display_name || other.processor_id}: ${other.version || "Version not recorded"}`),
    run.model !== "Not used" ? `Additional LLM: ${run.model}` : null].filter(Boolean).join(" · ");
}

export function engineKey(run: Evaluation): string {
  return run.steps?.includes("document_ai_extract")
    ? JSON.stringify([run.extraction_engine?.project_id, run.extraction_engine?.location, run.extraction_engine?.processor_id, run.extraction_engine?.version, run.extraction_engine?.additional_processors?.map(other => [other.project_id, other.location, other.processor_id, other.version]), run.model, run.provider])
    : run.model;
}


/** Keep dates and full resource IDs in details; only shorten known Google names. */
export function compactExtractorVersion(version: string | null | undefined): string {
  if (!version) return "Version unavailable";
  const foundation = /^pretrained-foundation-model-v(.+?)(?:-\d{4}-\d{2}-\d{2})?$/.exec(version);
  return foundation
    ? `Foundation ${foundation[1].replace(/-lite$/, " Lite").replace(/-pro$/, " Pro")}`
    : `Version ${version}`;
}
