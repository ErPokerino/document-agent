import { defaultConfigFor, stepLabel } from "./pipeline-editor.ts";
import { isPdfTextFallback } from "./pipeline-steps.ts";
import type { PipelineStep, StepKind } from "./types";

export type FlowCategory = "document" | "reader" | "model" | "transform" | "reference";

export function flowCategory(kind: StepKind): FlowCategory {
  if (kind === "render_pages" || kind === "read_pdf_text") return "document";
  if (kind === "document_ai_ocr" || kind === "document_ai_layout") return "reader";
  if (kind === "llm_extract" || kind === "document_ai_extract" || kind === "artifact_predict") return "model";
  if (kind === "master_data_lookup") return "reference";
  return "transform";
}

/** Edges describe the compiler's sequence, including repeated kinds. No saved config is rewritten. */
export function pipelineFlow(steps: PipelineStep[]) {
  const nodes = [
    { id: "input", label: "PDF document", index: null, category: "document" as FlowCategory },
    ...steps.map((step, index) => ({
      id: `step-${index}`, label: stepLabel(step.kind), index,
      category: flowCategory(step.kind), conditional: isPdfTextFallback(step),
    })),
    { id: "output", label: "Extracted fields", index: null, category: "document" as FlowCategory },
  ];
  const edges = nodes.slice(0, -1).map((node, index) => ({
    id: `${node.id}-${nodes[index + 1].id}`,
    source: node.id, target: nodes[index + 1].id, insertAt: index,
  }));
  return { nodes, edges };
}

/** Inserting between two nodes retains every existing step and its processor options. */
export function insertFlowStep(steps: PipelineStep[], at: number, kind: StepKind): PipelineStep[] {
  const index = Math.max(0, Math.min(steps.length, at));
  return [...steps.slice(0, index), { kind, config: defaultConfigFor(kind) }, ...steps.slice(index)];
}

export function stepProblems(problems: string[], index: number): string[] {
  return problems.filter(problem => new RegExp(`^Step ${index + 1}(?:\\b|:)`, "i").test(problem));
}
