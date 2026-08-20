import type { PromptConfiguration } from "./types";

// Mirrors the Pydantic bounds: EntityDefinition.name pattern and
// AppSettings.max_pages_to_analyze ge=1 le=100.
const ENTITY_NAME = /^[a-z][a-z0-9_]*$/;
const MIN_PAGES = 1;
const MAX_PAGES = 100;

/**
 * Client-side copy of the backend validation, so the user sees the problem
 * before a round trip. The backend stays the authority: it re-validates.
 */
export function validateSettingsDraft(
  prompts: PromptConfiguration,
  pageLimitInput: string,
): string | null {
  const names = prompts.entities.map((entity) => entity.name);

  if (names.some((name) => !ENTITY_NAME.test(name))) {
    return "Names must start with a lowercase letter and contain only letters, numbers and underscores.";
  }
  if (new Set(names).size !== names.length) {
    return "Entity names must be unique.";
  }
  if (prompts.entities.some((entity) => !entity.description.trim())) {
    return "Every entity must have a description.";
  }
  if (
    !prompts.system_prompt.trim() ||
    !prompts.user_prompt.trim() ||
    !prompts.confidence_prompt.trim()
  ) {
    return "Prompts cannot be empty.";
  }

  const pageLimit = Number(pageLimitInput);
  if (!/^\d+$/.test(pageLimitInput) || pageLimit < MIN_PAGES || pageLimit > MAX_PAGES) {
    return `Maximum pages must be an integer between ${MIN_PAGES} and ${MAX_PAGES}.`;
  }
  return null;
}
