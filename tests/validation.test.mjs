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
  assert.equal(validateSettingsDraft(draft(), "10"), null);
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
  const error = validateSettingsDraft(draft({ entities: [entity, { ...entity }] }), "10");

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
  assert.match(validateSettingsDraft(draft({ system_prompt: "   " }), "10") ?? "", /Prompts/);
});

test("the page limit must be an integer inside the backend range", () => {
  assert.equal(validateSettingsDraft(draft(), "1"), null);
  assert.equal(validateSettingsDraft(draft(), "100"), null);
  assert.match(validateSettingsDraft(draft(), "0") ?? "", /between 1 and 100/);
  assert.match(validateSettingsDraft(draft(), "101") ?? "", /between 1 and 100/);
  assert.match(validateSettingsDraft(draft(), "2.5") ?? "", /between 1 and 100/);
  assert.match(validateSettingsDraft(draft(), "") ?? "", /between 1 and 100/);
});
