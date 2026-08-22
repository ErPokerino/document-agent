import type { EntityFormat } from "./types";
import type { LabelMode } from "./labels";

export const formatLabels: Record<EntityFormat, string> = {
  text: "Text",
  date: "Date · YYYY-MM-DD",
  currency: "Currency · ISO 4217",
  decimal: "Decimal number",
  integer: "Integer number",
};

export const labelModes: Record<LabelMode, string> = {
  skip: "Not labelled",
  value: "Value",
  absent: "Absent in document",
};

export function percent(accuracy: number | null | undefined): string {
  return accuracy === null || accuracy === undefined ? "—" : `${Math.round(accuracy * 100)}%`;
}

/** Bands for colouring a score. Deliberately blunt: good, fair, poor. */
export function accuracyClass(accuracy: number | null | undefined): string {
  if (accuracy === null || accuracy === undefined) return "";
  if (accuracy >= 0.9) return "good";
  if (accuracy >= 0.6) return "fair";
  return "poor";
}

export function seconds(ms: number | null | undefined): string {
  return ms === null || ms === undefined ? "—" : `${(ms / 1000).toFixed(1)} s`;
}

export function describeValue(value: unknown): string {
  return value === null || value === undefined ? "—" : String(value);
}
