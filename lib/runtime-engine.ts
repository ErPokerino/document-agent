import { formatBytes } from "./format.ts";
import type { RuntimeEngineInfo } from "./types.ts";

/**
 * What LM Studio's selected engine means for the model on screen.
 *
 * DocuFlow loads a large model with `--gpu off`, and used to report that as
 * the model being kept off the integrated GPU. Only its layers are. The
 * vision projector follows the selected engine, so on a Vulkan build the page
 * image is encoded on the GPU whatever the load flags said — which is where
 * an integrated adapter loses its device and takes the run with it.
 *
 * The description states where the work runs. What to do about it depends on
 * what the machine is for, which the app is in no position to judge.
 */
export function describeRuntimeEngine(
  info: RuntimeEngineInfo | null,
  model: { vision: boolean; safeProfile: boolean },
): string | null {
  if (!info?.engine) return null;
  const name = info.engine.split("@")[0];

  if (!info.uses_gpu) {
    return `LM Studio is running ${name}, a build with no accelerator support, so every part of this model runs on the processor.`;
  }
  if (!model.safeProfile) {
    return `LM Studio is running ${name}, which offloads to this machine's GPU.`;
  }
  if (!model.vision) {
    return `LM Studio is running ${name}, which offloads to the GPU, but this model's layers are held on the processor.`;
  }
  return `LM Studio is running ${name}, which offloads to the GPU. This model's layers are held on the processor; its vision encoder is not, so each page image is encoded on the GPU.`;
}

/**
 * The machine DocuFlow found, and the budget it derived from it.
 *
 * This is the number that decides how every local model here is loaded, and
 * it is computed from the host rather than fixed in the code — so on a machine
 * the app has never seen, this line is the way to check what it concluded.
 */
export function describeHost(info: RuntimeEngineInfo | null): string | null {
  if (!info || info.offload_budget_bytes === null || info.offload_budget_bytes === undefined) {
    return null;
  }
  if (!info.accelerator || !info.accelerator_bytes) {
    return "The selected runtime reports no accelerator, so every model is loaded on the processor.";
  }
  // An integrated adapter's figure is a slice of system memory, and a single
  // allocation cannot count on all of it. Saying so explains the gap between
  // the two numbers on the same line.
  const memory = info.accelerator_integrated
    ? `${formatBytes(info.accelerator_bytes)} shared with system memory`
    : `${formatBytes(info.accelerator_bytes)} dedicated`;
  return (
    `${info.accelerator} — ${memory}. DocuFlow offloads models up to ` +
    `${formatBytes(info.offload_budget_bytes)} to it, and holds larger ones on the processor.`
  );
}
