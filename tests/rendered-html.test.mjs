import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the DocuFlow workspace", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>DocuFlow/);
  assert.match(html, /Document workspace/);
  assert.match(html, /Upload invoice/);
  assert.match(html, /Model-estimated confidence/);
  assert.match(html, /Large files follow the configured page limit/);
  assert.doesNotMatch(html, /codex-preview|SkeletonPreview/);
});

test("reviewed values can be edited and exported", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(source, /placeholder="Enter value"/);
  assert.match(source, /manually_edited/);
  assert.match(source, /Restore model value/);
  assert.match(source, /Maximum pages per extraction/);
  assert.doesNotMatch(source, /Input token budget/);
  assert.match(source, /disk/);
  assert.match(source, /Structured output is enabled/);
  assert.match(source, /refreshed every 10 seconds/);
  assert.match(source, /Load & warm up/);
  assert.match(source, /model load excluded/);
  assert.match(source, /pageLimitInput/);
  assert.match(source, /activeModel\?\.ready === true/);
  assert.match(source, /Warming up model/);
  assert.match(source, /Large models use a CPU-safe profile/);
  assert.match(source, /Prompt and image to first token/);
  assert.match(source, /prompt and image cache/);
  assert.doesNotMatch(source, /context_length \/ 1024/);
});
