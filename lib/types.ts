// Generated from the FastAPI OpenAPI schema. Do not edit by hand.
// Regenerate with: .venv/Scripts/python.exe backend/scripts/generate_types.py
//
// Every property is emitted as required: FastAPI serializes response models in
// full, defaults included, and the frontend always sends complete objects back.

export type EntityFormat = "text" | "date" | "currency" | "decimal" | "integer";

export type Confidence = FieldExtraction["confidence"];

export type ModelRuntimeState = ModelInfo["runtime_state"];

export type AppSettings = {
  model: string;
  excluded_model_ids: string[];
  lm_studio_url: string;
  max_pages_to_analyze: number;
  prompts: PromptConfiguration;
};

export type EntityDefinition = {
  name: string;
  format: EntityFormat;
  description: string;
};

export type ExtractionResponse = {
  document_type: string;
  filename: string;
  model: string;
  elapsed_ms: number;
  data: Record<string, FieldExtraction>;
  processing: ProcessingInfo;
};

export type FieldExtraction = {
  value: string | number | null;
  confidence: "low" | "medium" | "high";
  warning: string | null;
};

export type HealthStatus = {
  status: string;
  lm_studio: boolean;
  active_model: string;
};

export type ModelInfo = {
  id: string;
  name: string;
  parameters: string | null;
  quantization: string | null;
  size_bytes: number | null;
  context_length: number | null;
  loaded: boolean;
  ready: boolean;
  runtime_state: "not_loaded" | "loaded" | "loading" | "warming_up" | "ready" | "error";
  vision: boolean;
};

export type ModelLoadRequest = {
  model: string;
};

export type ModelLoadResponse = {
  model: string;
  status: "ready";
  load_ms: number;
  warmup_ms: number;
  total_ms: number;
  unloaded_models: number;
  profile: "default" | "compatibility";
  already_loaded: boolean;
  already_ready: boolean;
  warmup_mode: "vision" | "vision_and_schema";
  preparation_attempts: number;
};

export type ProcessingInfo = {
  page_count: number;
  processed_pages: number;
  first_processed_page: number;
  last_processed_page: number;
  cut_applied: boolean;
  single_call_page_limit: number;
  configured_page_limit: number;
  time_to_first_token_seconds: number | null;
  prediction_time_seconds: number | null;
  tokens_per_second: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
};

export type PromptConfiguration = {
  system_prompt: string;
  user_prompt: string;
  confidence_prompt: string;
  entities: EntityDefinition[];
};
