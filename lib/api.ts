import type { AppSettings, ExtractionResponse, HealthStatus, ModelInfo, ModelLoadResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg ?? String(item)).join(" · ")
      : detail;
    throw new Error(message ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthStatus>("/api/health"),
  models: () => request<ModelInfo[]>("/api/models"),
  loadModel: (model: string) =>
    request<ModelLoadResponse>("/api/models/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }),
  settings: () => request<AppSettings>("/api/settings"),
  saveSettings: (settings: AppSettings) =>
    request<AppSettings>("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),
  extract: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ExtractionResponse>("/api/documents/extract", {
      method: "POST",
      body: form,
    });
  },
};
