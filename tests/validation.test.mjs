import assert from "node:assert/strict";
import test from "node:test";

import { validateSettingsDraft } from "../lib/validation.ts";

const prompts = {
  system_prompt: "system",
  user_prompt: "user",
  confidence_prompt: "confidence",
  entities: [{ name: "total_amount", format: "decimal", description: "The total." }],
};

const draft = (overrides = {}) => ({ ...prompts, ...overrides });

test("a well formed draft has no error", () => {
  assert.equal(validateSettingsDraft(draft()), null);
});

test("an entity name that is not a valid JSON key is rejected", () => {
  const error = validateSettingsDraft(
    draft({ entities: [{ name: "2fast", format: "text", description: "x" }] }),
    "10",
  );

  assert.match(error ?? "", /lowercase letter/);
});

test("duplicate entity names are rejected", () => {
  const entity = { name: "total_amount", format: "decimal", description: "x" };
  const error = validateSettingsDraft(draft({ entities: [entity, { ...entity }] }));

  assert.match(error ?? "", /unique/);
});

test("an entity without a description is rejected", () => {
  const error = validateSettingsDraft(
    draft({ entities: [{ name: "total_amount", format: "decimal", description: "  " }] }),
    "10",
  );

  assert.match(error ?? "", /description/);
});

test("an empty prompt is rejected", () => {
  assert.match(validateSettingsDraft(draft({ system_prompt: "   " })) ?? "", /Prompts/);
});
