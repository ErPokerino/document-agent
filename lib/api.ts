import type {
  AppSettings,
  Dataset,
  DatasetDocument,
  DocumentLabels,
  DraftLabels,
  Evaluation,
  EvaluationDetail,
  ExtractionResponse,
  ExtractionRun,
  GcpKeyStatus,
  GeminiKeyStatus,
  HealthStatus,
  ModelInfo,
  ModelLoadResponse,
  PipelineDefinition,
  PromptConfiguration,
  PromptPreview,
  MasterDataTable,
  SavedPipeline,
  StepCatalogueEntry,
} from "./types";

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
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function upload(file: File): RequestInit {
  const form = new FormData();
  form.append("file", file);
  return { method: "POST", body: form };
}

const segment = encodeURIComponent;

/** Direct links, for an <iframe> preview and for a browser download. */
export const apiUrls = {
  documentFile: (dataset: string, document: string) =>
    `${API_BASE}/api/datasets/${segment(dataset)}/documents/${segment(document)}/file`,
  evaluationCsv: (id: number) => `${API_BASE}/api/evaluations/${id}/export.csv`,
};

export const api = {
  health: () => request<HealthStatus>("/api/health"),
  models: () => request<ModelInfo[]>("/api/models"),
  loadModel: (model: string) => request<ModelLoadResponse>("/api/models/load", json("POST", { model })),
  settings: () => request<AppSettings>("/api/settings"),
  saveSettings: (settings: AppSettings) => request<AppSettings>("/api/settings", json("PUT", settings)),
  extract: (file: File) => request<ExtractionResponse>("/api/documents/extract", upload(file)),

  previewPrompt: (prompts: PromptConfiguration, provider: AppSettings["provider"]) =>
    request<PromptPreview>("/api/prompts/preview", json("POST", { prompts, provider })),
  geminiKeyStatus: () => request<GeminiKeyStatus>("/api/settings/gemini"),
  verifyGeminiKey: () => request<GeminiKeyStatus>("/api/settings/gemini/verify", { method: "POST" }),
  clearGeminiKey: () => request<void>("/api/settings/gemini", { method: "DELETE" }),
  gcpKeyStatus: () => request<GcpKeyStatus>("/api/settings/gcp"),
  verifyGcpKey: () => request<GcpKeyStatus>("/api/settings/gcp/verify", { method: "POST" }),

  runs: (validatedOnly = false) =>
    request<ExtractionRun[]>(`/api/runs?validated_only=${validatedOnly}`),
  saveCorrections: (runId: number, corrections: Record<string, unknown>) =>
    request<void>(`/api/runs/${runId}/corrections`, json("POST", { corrections })),

  datasets: () => request<Dataset[]>("/api/datasets"),
  createDataset: (name: string) => request<Dataset>("/api/datasets", json("POST", { name })),
  renameDataset: (name: string, newName: string) =>
    request<Dataset>(`/api/datasets/${segment(name)}`, json("PATCH", { name: newName })),
  deleteDataset: (name: string) => request<void>(`/api/datasets/${segment(name)}`, { method: "DELETE" }),
  datasetDocuments: (name: string) =>
    request<DatasetDocument[]>(`/api/datasets/${segment(name)}/documents`),
  addDatasetDocument: (name: string, file: File) =>
    request<DatasetDocument>(`/api/datasets/${segment(name)}/documents`, upload(file)),
  removeDatasetDocument: (name: string, document: string) =>
    request<void>(`/api/datasets/${segment(name)}/documents/${segment(document)}`, { method: "DELETE" }),
  documentLabels: (name: string, document: string) =>
    request<DocumentLabels>(`/api/datasets/${segment(name)}/documents/${segment(document)}/labels`),
  saveDocumentLabels: (name: string, document: string, labels: Record<string, unknown>) =>
    request<DocumentLabels>(
      `/api/datasets/${segment(name)}/documents/${segment(document)}/labels`,
      json("PUT", { labels }),
    ),
  promoteRuns: (name: string, runIds: number[]) =>
    request<DatasetDocument[]>(
      `/api/datasets/${segment(name)}/documents/from-run`,
      json("POST", { run_ids: runIds }),
    ),
  draftLabels: (name: string, document: string) =>
    request<DraftLabels>(
      `/api/datasets/${segment(name)}/documents/${segment(document)}/draft-labels`,
      { method: "POST" },
    ),

  masterDataTables: () => request<MasterDataTable[]>("/api/master-data/tables"),
  masterDataRows: (
    table: string,
    options: {
      query?: string;
      sort?: string;
      descending?: boolean;
      filters?: Record<string, string>;
    } = {},
  ) => {
    const search = new URLSearchParams({
      query: options.query ?? "",
      sort: options.sort ?? "",
      descending: String(options.descending ?? false),
    });
    // One `filter=column:value` per narrowed column; the backend splits once,
    // so a value holding a colon survives.
    for (const [column, value] of Object.entries(options.filters ?? {})) {
      if (value.trim()) search.append("filter", `${column}:${value.trim()}`);
    }
    return request<Record<string, string>[]>(
      `/api/master-data/tables/${segment(table)}/rows?${search}`,
    );
  },
  addMasterDataRow: (table: string, values: Record<string, string>) =>
    request<Record<string, string>>(
      `/api/master-data/tables/${segment(table)}/rows`,
      json("POST", { values }),
    ),
  updateMasterDataRow: (table: string, identifier: string, values: Record<string, string>) =>
    request<Record<string, string>>(
      `/api/master-data/tables/${segment(table)}/rows/${segment(identifier)}`,
      json("PATCH", { values }),
    ),
  deleteMasterDataRow: (table: string, identifier: string) =>
    request<void>(`/api/master-data/tables/${segment(table)}/rows/${segment(identifier)}`, {
      method: "DELETE",
    }),
  seedMasterDataRows: (table: string) =>
    request<Record<string, string>[]>(
      `/api/master-data/tables/${segment(table)}/rows/from-datasets`,
      { method: "POST" },
    ),

  pipelines: () => request<SavedPipeline[]>("/api/pipelines"),
  pipelineSteps: () => request<StepCatalogueEntry[]>("/api/pipelines/steps"),
  checkPipeline: (definition: PipelineDefinition) =>
    request<SavedPipeline>("/api/pipelines/check", json("POST", definition)),
  savePipeline: (definition: PipelineDefinition) =>
    request<SavedPipeline>(`/api/pipelines/${segment(definition.name)}`, json("PUT", definition)),
  renamePipeline: (name: string, newName: string) =>
    request<SavedPipeline>(`/api/pipelines/${segment(name)}`, json("PATCH", { name: newName })),
  deletePipeline: (name: string) =>
    request<void>(`/api/pipelines/${segment(name)}`, { method: "DELETE" }),

  evaluations: () => request<Evaluation[]>("/api/evaluations"),
  evaluation: (id: number) => request<EvaluationDetail>(`/api/evaluations/${id}`),
  startEvaluation: (dataset: string) => request<Evaluation>("/api/evaluations", json("POST", { dataset })),
  cancelEvaluation: (id: number) => request<Evaluation>(`/api/evaluations/${id}/cancel`, { method: "POST" }),
  retryEvaluation: (id: number) => request<Evaluation>(`/api/evaluations/${id}/retry`, { method: "POST" }),
  deleteEvaluation: (id: number) => request<void>(`/api/evaluations/${id}`, { method: "DELETE" }),
};
