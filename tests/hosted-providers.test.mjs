import assert from "node:assert/strict";
import test from "node:test";

import { checkFor, controlsOf, draftLocation, effectiveRate, publisherOf, routeLabel, withControls, withRate } from "../lib/hosted-providers.ts";

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

test("every hosted model is reached through Vertex AI, unless Gemini uses a key", () => {
  assert.equal(routeLabel({ provider: "model_garden" }, vertex), "Vertex AI");
  assert.equal(routeLabel({ provider: "gemini" }, vertex), "Vertex AI");
  assert.equal(routeLabel({ provider: "gemini" }, { access: "api_key" }), "Gemini API");
});

const full = () => ({
  gemini: { location: null, thinking_level: "low", max_output_tokens: 16000 },
  model_garden: { claude_location: "eu", claude_effort: "low", claude_max_output_tokens: 4096, grok_location: "global", grok_effort: "low", grok_max_output_tokens: 4096 },
  hosted_rates: {},
});

test("each publisher has the same three controls, stored where its requests read them", () => {
  let settings = full();
  settings = withControls(settings, "google", { effort: "high", maxOutputTokens: 8000, location: "global" });
  settings = withControls(settings, "xai", { effort: "medium" });
  assert.deepEqual(controlsOf(settings, "google", vertex), { location: "global", effort: "high", maxOutputTokens: 8000 });
  assert.equal(settings.gemini.thinking_level, "high");
  assert.deepEqual(controlsOf(settings, "xai", vertex), { location: "global", effort: "medium", maxOutputTokens: 4096 });
  assert.deepEqual(controlsOf(settings, "anthropic", vertex), { location: "eu", effort: "low", maxOutputTokens: 4096 });
});

test("a rate is Google's until edited, and resetting returns to Google's", () => {
  const published = [{ model: "gemini-3.8-flash", location: "eu", input_per_million: 0.825, output_per_million: 4.125, cache_read_per_million: 0.0825 }];
  let settings = full();
  assert.deepEqual(effectiveRate(settings, published, "gemini-3.8-flash", "eu"), {
    rate: { input_per_million: 0.825, output_per_million: 4.125, cache_read_per_million: 0.0825 }, edited: false, google: published[0],
  });
  settings = withRate(settings, "gemini-3.8-flash@eu", { input_per_million: 1, output_per_million: 4.125, cache_read_per_million: null });
  assert.equal(effectiveRate(settings, published, "gemini-3.8-flash", "eu").edited, true);
  assert.equal(effectiveRate(settings, published, "gemini-3.8-flash", "eu").rate.cache_read_per_million, null);
  settings = withRate(settings, "gemini-3.8-flash@eu", null);
  assert.equal(effectiveRate(settings, published, "gemini-3.8-flash", "eu").rate.input_per_million, 0.825);
});
