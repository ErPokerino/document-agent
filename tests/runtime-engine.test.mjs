import assert from "node:assert/strict";
import test from "node:test";

import { describeRuntimeEngine } from "../lib/runtime-engine.ts";

const vulkan = { engine: "llama.cpp-win-x86_64-vulkan-avx2@2.29.1", uses_gpu: true };
const cpu = { engine: "llama.cpp-win-x86_64-avx2@2.29.1", uses_gpu: false };
const unknown = { engine: null, uses_gpu: false };

test("an accelerated engine is named, and so is the part it still runs", () => {
  const described = describeRuntimeEngine(vulkan, { vision: true, safeProfile: true });
  assert.match(described ?? "", /vulkan/);
  // The claim this corrects: the app used to say a large model was kept off
  // the GPU, when only its layers were.
  assert.match(described ?? "", /page image/i);
});

test("a model that is never shown an image is not told about the image path", () => {
  const described = describeRuntimeEngine(vulkan, { vision: false, safeProfile: true });
  assert.doesNotMatch(described ?? "", /page image/i);
});

test("a processor-only engine leaves nothing on an accelerator", () => {
  const described = describeRuntimeEngine(cpu, { vision: true, safeProfile: true });
  assert.match(described ?? "", /processor/i);
  assert.doesNotMatch(described ?? "", /page image is encoded on the GPU/i);
});

test("an engine that could not be read is not described", () => {
  assert.equal(describeRuntimeEngine(unknown, { vision: true, safeProfile: true }), null);
  assert.equal(describeRuntimeEngine(null, { vision: true, safeProfile: true }), null);
});

test("nothing is recommended", () => {
  for (const info of [vulkan, cpu]) {
    for (const vision of [true, false]) {
      const described = describeRuntimeEngine(info, { vision, safeProfile: true }) ?? "";
      assert.doesNotMatch(described, /instead|should|try |switch to|recommend/i);
    }
  }
});
