import type { AppSettings, HealthStatus, ModelInfo } from "./types";

export type BootstrapResult = {
  health: HealthStatus | null;
  settings: AppSettings | null;
  models: ModelInfo[];
  error: string | null;
};

function valueOrNull<T>(result: PromiseSettledResult<T>): T | null {
  return result.status === "fulfilled" ? result.value : null;
}

function reasonMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

/**
 * Health and model discovery are allowed to fail: the UI already renders an
 * offline state for both. A failed settings load is different — without it the
 * app has nothing to edit, and falling back to hardcoded defaults would let
 * Save overwrite the stored prompts. That case is reported instead.
 */
export function resolveBootstrap(
  [health, settings, models]: [
    PromiseSettledResult<HealthStatus>,
    PromiseSettledResult<AppSettings>,
    PromiseSettledResult<ModelInfo[]>,
  ],
): BootstrapResult {
  const loadedSettings = valueOrNull(settings);
  const loadedModels = valueOrNull(models) ?? [];
  let reconciledSettings = loadedSettings;
  if (loadedSettings?.model && loadedSettings.provider !== "gemini") {
    const exact = loadedModels.find((model) => model.id === loadedSettings.model);
    const leaf = loadedSettings.model.split("/").at(-1)?.toLocaleLowerCase();
    const aliases = exact
      ? []
      : loadedModels.filter(
          (model) => model.provider !== "gemini" && model.id.split("/").at(-1)?.toLocaleLowerCase() === leaf,
        );
    const resolved = exact ?? (aliases.length === 1 ? aliases[0] : null);
    if (resolved && resolved.id !== loadedSettings.model) {
      // The models request also persists this migration on the backend. This
      // copy prevents the first paint from waiting for the next 10 s refresh.
      reconciledSettings = { ...loadedSettings, model: resolved.id };
    }
  }
  return {
    health: valueOrNull(health),
    settings: reconciledSettings,
    models: loadedModels,
    error:
      settings.status === "rejected"
        ? `Settings could not be loaded: ${reasonMessage(settings.reason)}`
        : null,
  };
}
