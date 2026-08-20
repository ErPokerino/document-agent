import assert from "node:assert/strict";
import test from "node:test";

import { resolveBootstrap } from "../lib/bootstrap.ts";

const health = { status: "ok", lm_studio: true, active_model: "vision-model" };
const settings = {
  model: "vision-model",
  excluded_model_ids: [],
  lm_studio_url: "http://127.0.0.1:1234",
  max_pages_to_analyze: 10,
  prompts: { system_prompt: "s", user_prompt: "u", confidence_prompt: "c", entities: [] },
};
const models = [{ id: "vision-model", name: "Vision Model" }];

const fulfilled = (value) => ({ status: "fulfilled", value });
const rejected = (reason) => ({ status: "rejected", reason });

test("a successful bootstrap exposes every value and no error", () => {
  const result = resolveBootstrap([fulfilled(health), fulfilled(settings), fulfilled(models)]);

  assert.deepEqual(result.settings, settings);
  assert.deepEqual(result.models, models);
  assert.deepEqual(result.health, health);
  assert.equal(result.error, null);
});

test("a failed settings load is surfaced instead of being swallowed", () => {
  const result = resolveBootstrap([
    fulfilled(health),
    rejected(new Error("Request failed (500)")),
    fulfilled(models),
  ]);

  assert.equal(result.settings, null);
  assert.match(result.error ?? "", /Request failed \(500\)/);
});

test("settings are never replaced by a local fallback when the load fails", () => {
  const result = resolveBootstrap([fulfilled(health), rejected(new Error("boom")), fulfilled(models)]);

  // A non-null value here would let Save overwrite the stored prompts with
  // hardcoded frontend defaults.
  assert.equal(result.settings, null);
});

test("an unreachable backend still reports the settings failure", () => {
  const result = resolveBootstrap([
    rejected(new Error("fetch failed")),
    rejected(new Error("fetch failed")),
    rejected(new Error("fetch failed")),
  ]);

  assert.equal(result.health, null);
  assert.deepEqual(result.models, []);
  assert.equal(result.settings, null);
  assert.match(result.error ?? "", /fetch failed/);
});

test("a failing health probe alone does not block the settings screen", () => {
  const result = resolveBootstrap([rejected(new Error("offline")), fulfilled(settings), fulfilled(models)]);

  assert.deepEqual(result.settings, settings);
  assert.equal(result.error, null);
});

test("a failing model discovery alone does not block the settings screen", () => {
  const result = resolveBootstrap([fulfilled(health), fulfilled(settings), rejected(new Error("503"))]);

  assert.deepEqual(result.settings, settings);
  assert.deepEqual(result.models, []);
  assert.equal(result.error, null);
});
