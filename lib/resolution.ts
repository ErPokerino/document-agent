/**
 * Methods and strategies, as the Resolve step and the Lab present them.
 *
 * Method names mirror `method_names` in the backend engine: a step's kind, a
 * trained model's name, and a number when a pipeline repeats a kind. They have
 * to agree, because a priority list names methods and the backend looks them
 * up by these exact strings.
 */

import type { ArtifactSummary, FieldRule, PipelineStep, ResolutionConfig } from "./types";

export const STRATEGY_LABELS: Record<FieldRule["strategy"], string> = {
  last: "Last step to write it",
  priority: "First in priority order",
  best_confidence: "Most confident",
  agreement: "What most methods agree on",
};

export const STRATEGY_HELP: Record<FieldRule["strategy"], string> = {
  last: "The value the last step to write the field left. What every pipeline did before candidates existed.",
  priority: "The first method in the list that proposed a usable value. A method not listed is not consulted.",
  best_confidence: "The candidate with the highest confidence, then the highest score. Later steps win ties.",
  agreement: "The value most methods proposed, each method counted once. An even split leaves the field empty and says so; a unanimous answer from two or more methods is high confidence.",
};

// Steps that only choose, or only state that a field is empty, propose nothing.
const NOT_METHODS = new Set(["resolve_candidates", "render_pages", "read_pdf_text", "document_ai_ocr", "document_ai_layout"]);

function methodOf(step: Pick<PipelineStep, "kind" | "config">, artifacts: Pick<ArtifactSummary, "id" | "name">[]): string {
  if (step.kind === "artifact_predict") {
    const artifact = artifacts.find((entry) => entry.id === step.config.artifact_id);
    return `trained: ${artifact?.name ?? String(step.config.artifact_id ?? "")}`;
  }
  return step.kind;
}

/** The methods the steps before `index` contribute, named as the backend names them. */
export function upstreamMethods(
  steps: Pick<PipelineStep, "kind" | "config">[],
  index: number,
  artifacts: Pick<ArtifactSummary, "id" | "name">[],
): string[] {
  const names = steps.map((step) => methodOf(step, artifacts));
  const counts = new Map<string, number>();
  for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1);
  const seen = new Map<string, number>();
  const numbered = names.map((name) => {
    seen.set(name, (seen.get(name) ?? 0) + 1);
    return (counts.get(name) ?? 0) > 1 ? `${name} #${seen.get(name)}` : name;
  });
  return numbered.filter((_, position) => position < index && !NOT_METHODS.has(steps[position].kind));
}

export function defaultResolution(): ResolutionConfig {
  return { default: { strategy: "last", priority: [], minimum_score: null }, fields: {} };
}

export function resolutionOf(config: Record<string, unknown>): ResolutionConfig {
  const given = config as Partial<ResolutionConfig>;
  return {
    default: { ...defaultResolution().default, ...(given.default ?? {}) },
    fields: given.fields ?? {},
  };
}

export function moveInList(list: string[], index: number, offset: number): string[] {
  const target = index + offset;
  if (target < 0 || target >= list.length) return list;
  const next = [...list];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** The priority as shown: the saved order, then any upstream method it does not list yet. */
export function priorityWithAll(priority: string[], methods: string[]): string[] {
  return [...priority.filter((method) => methods.includes(method)), ...methods.filter((method) => !priority.includes(method))];
}

export function describeRule(rule: FieldRule): string {
  if (rule.strategy !== "priority") return STRATEGY_LABELS[rule.strategy];
  return rule.priority.length ? `Priority: ${rule.priority.join(" → ")}` : "Priority: nothing listed";
}
