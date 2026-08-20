import type { EntityDefinition } from "./types";

/**
 * Ground truth has three states per entity, and collapsing the last two is what
 * makes evaluation metrics lie:
 *
 *   skip   - nobody reviewed this field; it is excluded from scoring
 *   value  - the document says this
 *   absent - the document says nothing, so the model must return null
 */
export type LabelMode = "skip" | "value" | "absent";
export type LabelDraft = { mode: LabelMode; text: string };

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
const INTEGER = /^[+-]?\d+$/;

export function labelsToDraft(
  labels: Record<string, unknown>,
  entities: EntityDefinition[],
): Record<string, LabelDraft> {
  return Object.fromEntries(
    entities.map((entity) => {
      if (!(entity.name in labels)) return [entity.name, { mode: "skip", text: "" }];
      const value = labels[entity.name];
      if (value === null) return [entity.name, { mode: "absent", text: "" }];
      return [entity.name, { mode: "value", text: String(value) }];
    }),
  );
}

export function draftToLabels(
  draft: Record<string, LabelDraft>,
  entities: EntityDefinition[],
): { labels: Record<string, string | number | null>; errors: string[] } {
  const labels: Record<string, string | number | null> = {};
  const errors: string[] = [];

  for (const entity of entities) {
    const entry = draft[entity.name];
    if (!entry || entry.mode === "skip") continue;
    if (entry.mode === "absent") {
      labels[entity.name] = null;
      continue;
    }

    const text = entry.text.trim();
    if (!text) continue;

    if (entity.format === "decimal" || entity.format === "integer") {
      const pattern = entity.format === "decimal" ? DECIMAL : INTEGER;
      if (!pattern.test(text)) {
        errors.push(`${entity.name} must be a ${entity.format} number, got "${text}".`);
        continue;
      }
      labels[entity.name] = Number(text);
      continue;
    }

    labels[entity.name] = entity.format === "currency" ? text.toUpperCase() : text;
  }

  return { labels, errors };
}
