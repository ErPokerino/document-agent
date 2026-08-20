import type { Confidence, EntityDefinition, FieldExtraction } from "./types";

export type ReviewedField = {
  value: string | number | null;
  confidence: Confidence;
  manually_edited: boolean;
  warning?: string;
};

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
const INTEGER = /^[+-]?\d+$/;

/**
 * A reviewed value is only converted to a number when the text is a well formed
 * one. `Number("1.234,56")` is NaN, and JSON.stringify writes NaN as null, which
 * used to discard what the reviewer had typed; `parseInt("12.7")` silently
 * truncated it. Keeping the raw text makes a bad entry visible in the export.
 */
function parseValue(raw: string, format: EntityDefinition["format"]): string | number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (format === "decimal") return DECIMAL.test(trimmed) ? Number(trimmed) : trimmed;
  if (format === "integer") return INTEGER.test(trimmed) ? Number(trimmed) : trimmed;
  return trimmed;
}

export function buildReviewedExport(
  entities: EntityDefinition[],
  data: Record<string, FieldExtraction>,
  editedValues: Record<string, string>,
  editedFields: ReadonlySet<string>,
): Record<string, ReviewedField> {
  return Object.fromEntries(
    entities.map((entity) => {
      // The entity list can contain a field the extraction never produced.
      const original = data[entity.name];
      const manuallyEdited = editedFields.has(entity.name);
      const warning = original?.warning;
      return [
        entity.name,
        {
          value: parseValue(editedValues[entity.name] ?? "", entity.format),
          confidence: original?.confidence ?? "low",
          manually_edited: manuallyEdited,
          ...(warning && !manuallyEdited ? { warning } : {}),
        },
      ];
    }),
  );
}
