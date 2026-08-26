import type { AppSettings, ModelInfo } from "./types";

type RunTargetSettings = Pick<AppSettings, "model" | "pipeline">;
type RunTargetModel = Pick<ModelInfo, "id" | "name">;

/** Describe exactly the saved configuration the backend will use for a Lab run. */
export function labRunTarget(
  settings: RunTargetSettings,
  activeModel: RunTargetModel | undefined,
) {
  return {
    pipeline: settings.pipeline,
    modelId: settings.model,
    modelName: activeModel?.id === settings.model ? activeModel.name : settings.model,
  };
}
