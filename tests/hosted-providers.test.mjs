import assert from "node:assert/strict";
import test from "node:test";

import { checkFor, draftLocation, publisherOf, routeLabel } from "../lib/hosted-providers.ts";

const settings = (gemini = {}, garden = {}) => ({
  gemini: { location: null, ...gemini },
  model_garden: { claude_location: "eu", grok_location: "global", ...garden },
});
const vertex = { access: "vertex", configured: true, vertex_location: "eu", deployment_location: "eu" };

test("a Gemini model belongs to Google even where the backend names no publisher", () => {
  assert.equal(publisherOf({ provider: "gemini", publisher: null }), "google");
  assert.equal(publisherOf({ provider: "model_garden", publisher: "anthropic" }), "anthropic");
  assert.equal(publisherOf({ provider: "lm_studio", publisher: null }), null);
});

test("the location on screen is the one checked, before it is saved", () => {
  assert.equal(draftLocation(settings({}, { claude_location: "global" }), "anthropic", vertex), "global");
  assert.equal(draftLocation(settings(), "xai", vertex), "global");
  // No choice in LLM: the deployment's location, not a guess.
  assert.equal(draftLocation(settings(), "google", vertex), "eu");
  assert.equal(draftLocation(settings({ location: "global" }), "google", vertex), "global");
  // With an API key there is no location to choose.
  assert.equal(draftLocation(settings({ location: "global" }), "google", { access: "api_key", configured: true }), null);
});

test("a check answers for its own location only", () => {
  const checks = [{ model: "claude-sonnet-5-5", location: "eu", status: "no_quota" }];
  assert.equal(checkFor(checks, "claude-sonnet-5-5", "eu")?.status, "no_quota");
  assert.equal(checkFor(checks, "claude-sonnet-5-5", "global"), undefined);
  assert.equal(checkFor(checks, "claude-sonnet-5-5", null), undefined);
});

test("the route names how a request reaches the model", () => {
  assert.equal(routeLabel({ provider: "model_garden" }, vertex), "Model Garden");
  assert.equal(routeLabel({ provider: "gemini" }, vertex), "Vertex AI");
  assert.equal(routeLabel({ provider: "gemini" }, { access: "api_key" }), "Gemini API");
});
