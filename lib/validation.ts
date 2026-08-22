import type { PromptConfiguration } from "./types";

// Mirrors the Pydantic bound on EntityDefinition.name. The page limit moved
// to the pipeline, and is validated where it is edited.
const ENTITY_NAME = /^[a-z][a-z0-9_]*$/;

/**
 * Client-side copy of the backend validation, so the user sees the problem
 * before a round trip. The backend stays the authority: it re-validates.
 */
export function validateSettingsDraft(prompts: PromptConfiguration): string | null {
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

  return null;
}
