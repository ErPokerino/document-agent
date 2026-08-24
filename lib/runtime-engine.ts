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
