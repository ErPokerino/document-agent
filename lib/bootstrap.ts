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
  return {
    health: valueOrNull(health),
    settings: valueOrNull(settings),
    models: valueOrNull(models) ?? [],
    error:
      settings.status === "rejected"
        ? `Settings could not be loaded: ${reasonMessage(settings.reason)}`
        : null,
  };
}
