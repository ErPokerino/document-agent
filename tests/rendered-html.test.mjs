import assert from "node:assert/strict";
import test from "node:test";

// Behaviour of the review export, the settings validation and the bootstrap
// resolution lives in review.test.mjs, validation.test.mjs and
// bootstrap.test.mjs. This file only covers what needs a real server render.

async function render(path = "/") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${path}`, { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("the workspace is server-rendered as HTML", async () => {
  const response = await render();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
});

test("the first paint shows the upload workspace, not a placeholder", async () => {
  const html = await (await render()).text();

  assert.match(html, /<title>DocuFlow/);
  assert.match(html, /Document workspace/);
  assert.match(html, /Upload invoice/);
  assert.match(html, /Model-estimated confidence/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview/);
});

test("no settings are rendered before the backend has answered", async () => {
  const html = await (await render()).text();

  // The frontend has no local copy of the defaults any more: rendering one
  // would let Save overwrite the prompts stored on disk.
  assert.doesNotMatch(html, /qwen\/qwen3\.8-27b/);
  assert.doesNotMatch(html, /Invoice issue date/);
  assert.doesNotMatch(html, /information extraction agent/);
});

test("the shell renders without a crash when every API call is pending", async () => {
  const html = await (await render()).text();

  // Server rendering runs with settings === null; the null guards must hold.
  assert.match(html, /No model selected/);
  assert.doesNotMatch(html, /Application error|Internal Server Error/);
});
