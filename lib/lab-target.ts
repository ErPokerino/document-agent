import type { AppSettings, ModelInfo } from "./types";

type RunTargetSettings = Pick<AppSettings, "model" | "pipeline">;
type RunTargetModel = Pick<ModelInfo, "id" | "name">;

/** Describe exactly the saved configuration the backend will use for a Lab run. */
export function labRunTarget(
  settings: RunTargetSettings,
  activeModel: RunTargetModel | undefined,
  modelIsUsed = true,
) {
  return {
    pipeline: settings.pipeline,
    modelId: modelIsUsed ? settings.model : "",
    modelName: modelIsUsed
      ? activeModel?.id === settings.model ? activeModel.name : settings.model
      : "Not used by this pipeline",
  };
}
