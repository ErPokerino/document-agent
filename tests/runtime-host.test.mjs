import assert from "node:assert/strict";
import test from "node:test";

import { describeHost } from "../lib/runtime-engine.ts";

const GB = 1024 ** 3;

const integrated = {
  engine: "llama.cpp-win-x86_64-vulkan-avx2@2.29.1",
  uses_gpu: true,
  accelerator: "Intel(R) UHD Graphics (Vulkan, Integrated)",
  accelerator_bytes: Math.round(19.82 * GB),
  accelerator_integrated: true,
  offload_budget_bytes: Math.round(19.82 * GB * 0.4),
};
const dedicated = {
  engine: "llama.cpp-win-x86_64-nvidia-cuda-avx2@2.29.1",
  uses_gpu: true,
  accelerator: "NVIDIA GeForce RTX 4090 (CUDA)",
  accelerator_bytes: Math.round(23.99 * GB),
  accelerator_integrated: false,
  offload_budget_bytes: Math.round(23.99 * GB * 0.9),
};
const none = {
  engine: "llama.cpp-win-x86_64-avx2@2.29.1",
  uses_gpu: false,
  accelerator: null,
  accelerator_bytes: null,
  accelerator_integrated: false,
  offload_budget_bytes: 0,
};
const unreadable = { engine: null, uses_gpu: false, offload_budget_bytes: null };

test("the accelerator is named, with the budget the app derived from it", () => {
  const described = describeHost(dedicated) ?? "";
  assert.match(described, /RTX 4090/);
  assert.match(described, /24\.0 GB/);
  // The number that decides every load on this machine has to be visible.
  assert.match(described, /21\.6 GB/);
});

test("shared memory is called shared, because the figure overstates it", () => {
  const described = describeHost(integrated) ?? "";
  assert.match(described, /shared/i);
  assert.match(described, /7\.9 GB/);
});

test("no accelerator is stated plainly, not as a fault", () => {
  const described = describeHost(none) ?? "";
  assert.match(described, /no accelerator/i);
  assert.match(described, /processor/i);
  assert.doesNotMatch(described, /error|problem|cannot|unsupported/i);
});

test("a machine that could not be read says so, because it changes every load", () => {
  // Without the LM Studio CLI there is no survey, so nothing can be offloaded
  // and every model goes to the processor. On a new machine that looks like a
  // fault in the app unless it says why.
  const described = describeHost(unreadable) ?? "";
  assert.match(described, /could not read/i);
  assert.match(described, /processor/i);
  assert.match(described, /lms|command line/i);
});

test("no answer at all is not described", () => {
  assert.equal(describeHost(null), null);
});

test("nothing is recommended and no duration is predicted", () => {
  for (const info of [integrated, dedicated, none]) {
    const described = describeHost(info) ?? "";
    assert.doesNotMatch(described, /instead|should|try |recommend|minute|second|faster|slower/i);
  }
});
