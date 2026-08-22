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

export function defaultConfigFor(kind: StepKind): Record<string, unknown> {
  if (kind === "render_pages") return { scale: DEFAULT_RENDER_SCALE };
  if (kind === "regex_refine") return { rules: [] };
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
  if (step.kind === "llm_extract") return "One call to the configured model";
  const count = rulesOf(step).length;
  return count === 1 ? "1 rule" : `${count} rules`;
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
