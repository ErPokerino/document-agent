/**
 * The editing operations behind the Pipeline section.
 *
 * Kept away from React so each one can be tested on its own: reordering steps
 * and rewriting a step's configuration is where an editor quietly loses a rule
 * or mutates the list it was handed.
 */

import type { PipelineStep, StepCatalogueEntry, StepKind } from "./types";

export type RuleSource = "value" | "text";
export type RuleWhen = "always" | "if_empty" | "if_low_confidence";

export type RegexRule = {
  entity: string;
  pattern: string;
  group: number | null;
  replacement: string;
  source: RuleSource;
  when: RuleWhen;
  note: string;
};

export const DEFAULT_RENDER_SCALE = 1.35;

export const DEFAULT_MINIMUM_SIMILARITY = 0.75;

export function defaultConfigFor(kind: StepKind): Record<string, unknown> {
  if (kind === "render_pages") return { scale: DEFAULT_RENDER_SCALE };
  if (kind === "regex_refine") return { rules: [] };
  if (kind === "master_data_lookup") {
    return {
      source_entity: "",
      target_entity: "",
      algorithm: "combined",
      minimum_similarity: DEFAULT_MINIMUM_SIMILARITY,
    };
  }
  // A Document AI step takes its processor from Settings unless it is told
  // otherwise, so it starts with nothing of its own.
  return {};
}

export function addStep(steps: PipelineStep[], kind: StepKind): PipelineStep[] {
  return [...steps, { kind, config: defaultConfigFor(kind) }];
}

export function removeStep(steps: PipelineStep[], index: number): PipelineStep[] {
  return steps.filter((_, position) => position !== index);
}

export function moveStep(steps: PipelineStep[], index: number, offset: number): PipelineStep[] {
  const target = index + offset;
  if (target < 0 || target >= steps.length) return steps;
  const reordered = [...steps];
  [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
  return reordered;
}

export function setStepConfig(
  steps: PipelineStep[],
  index: number,
  config: Record<string, unknown>,
): PipelineStep[] {
  return steps.map((step, position) => (position === index ? { ...step, config } : step));
}

export function rulesOf(step: PipelineStep): RegexRule[] {
  if (step.kind !== "regex_refine") return [];
  const rules = (step.config as { rules?: RegexRule[] }).rules;
  return Array.isArray(rules) ? rules : [];
}

export function emptyRule(entity: string): RegexRule {
  return { entity, pattern: "", group: null, replacement: "", source: "value", when: "always", note: "" };
}

export function summarizeStep(step: PipelineStep): string {
  if (step.kind === "render_pages") {
    const scale = Number((step.config as { scale?: number }).scale ?? DEFAULT_RENDER_SCALE);
    return `Page images at ${scale}× zoom`;
  }
  if (step.kind === "document_ai_ocr") return "OCR text from Document AI";
  if (step.kind === "document_ai_layout") return "Text and layout from Document AI";
  if (step.kind === "llm_extract") return "One call to the configured model";
  if (step.kind === "master_data_lookup") {
    const config = step.config as { source_entity?: string; target_entity?: string };
    if (!config.source_entity || !config.target_entity) return "Lookup not configured";
    return `${config.source_entity} → ${config.target_entity}`;
  }
  if (step.kind === "regex_refine") {
    const count = rulesOf(step).length;
    return count === 1 ? "1 rule" : `${count} rules`;
  }
  return step.kind;
}

/** The human names of a pipeline's steps, for showing the shape of a run. */
export function stepLabels(
  steps: PipelineStep[],
  catalogue: Pick<StepCatalogueEntry, "kind" | "label">[],
): string[] {
  return steps.map((step) => catalogue.find((entry) => entry.kind === step.kind)?.label ?? step.kind);
}

export const MIN_PAGES = 1;
export const MAX_PAGES = 100;

/** Mirrors the Pydantic bound on PipelineDefinition.page_limit. */
export function pageLimitProblem(input: string): string | null {
  const value = Number(input);
  if (!/^\d+$/.test(input) || value < MIN_PAGES || value > MAX_PAGES) {
    return `The page limit must be a whole number between ${MIN_PAGES} and ${MAX_PAGES}.`;
  }
  return null;
}

export type CatalogueGroup = {
  title: string;
  blurb: string;
  entries: Pick<StepCatalogueEntry, "kind" | "label">[];
};

// Three questions, in the order a pipeline answers them: what is on the page,
// what does a model make of it, and what follows from that. A step nobody
// placed lands in the last group rather than disappearing.
const GROUPS: { title: string; blurb: string; kinds: string[] }[] = [
  {
    title: "Read the document",
    blurb: "Turn the PDF into something a later step can use.",
    kinds: ["render_pages", "document_ai_ocr", "document_ai_layout"],
  },
  { title: "Ask a model", blurb: "One call that fills the extracted fields.", kinds: ["llm_extract"] },
  {
    title: "Derived",
    blurb: "Work out a field the document never carried, from the ones it did.",
    kinds: ["master_data_lookup"],
  },
  {
    title: "Post processing",
    blurb: "Tidy up values that are already there, extracted or derived alike.",
    kinds: ["regex_refine"],
  },
];

export function groupCatalogue(
  catalogue: Pick<StepCatalogueEntry, "kind" | "label">[],
): CatalogueGroup[] {
  const placed = new Set(GROUPS.flatMap((group) => group.kinds));
  const groups = GROUPS.map((group) => ({
    title: group.title,
    blurb: group.blurb,
    entries: group.kinds
      .map((kind) => catalogue.find((entry) => entry.kind === kind))
      .filter((entry): entry is Pick<StepCatalogueEntry, "kind" | "label"> => entry !== undefined),
  }));
  const unplaced = catalogue.filter((entry) => !placed.has(entry.kind));
  if (unplaced.length) groups[groups.length - 1].entries.push(...unplaced);
  return groups.filter((group) => group.entries.length > 0);
}

/** What a step kind is called, without needing the backend catalogue.

    Used where a recorded run is shown: a run from months ago names step kinds
    that must stay readable even if the catalogue changes around them.
 */
export const STEP_LABELS: Record<string, string> = {
  render_pages: "Render pages",
  document_ai_ocr: "Document AI OCR",
  document_ai_layout: "Document AI Layout Parser",
  llm_extract: "LLM extraction",
  regex_refine: "Regex refinement",
  master_data_lookup: "Master data lookup",
};

export function stepLabel(kind: string): string {
  return STEP_LABELS[kind] ?? kind;
}
