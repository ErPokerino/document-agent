// Generated from the FastAPI OpenAPI schema. Do not edit by hand.
// Regenerate with: .venv/Scripts/python.exe backend/scripts/generate_types.py
//
// Every property is emitted as required: FastAPI serializes response models in
// full, defaults included, and the frontend always sends complete objects back.

export type EntityFormat = "text" | "date" | "currency" | "decimal" | "integer";

export type StepKind = "render_pages" | "document_ai_ocr" | "document_ai_layout" | "document_ai_extract" | "llm_extract" | "regex_refine" | "master_data_lookup" | "supplier_rules";

export type Confidence = FieldExtraction["confidence"];

export type ModelRuntimeState = ModelInfo["runtime_state"];

export type AppSettings = {
  provider: "lm_studio" | "gemini";
  model: string;
  excluded_model_ids: string[];
  gemini: GeminiSettings;
  gcp: GcpSettings;
  lm_studio_url: string;
  pipeline: string;
  theme: "system" | "light" | "dark";
  prompts: PromptConfiguration;
};

export type CorrectionsRequest = {
  corrections: Record<string, unknown>;
};

export type Dataset = {
  name: string;
  document_count: number;
  labelled_count: number;
};

export type DatasetCreateRequest = {
  name: string;
};

export type DatasetDocument = {
  name: string;
  size_bytes: number;
  labelled: boolean;
  labelled_entities: string[];
  label_source: string | null;
  label_error: string | null;
};

export type DocumentLabels = {
  document: string;
  source: string;
  labels: Record<string, unknown>;
  updated_at: string | null;
};

export type DraftLabels = {
  document: string;
  labels: Record<string, unknown>;
  confidence: Record<string, string>;
  elapsed_ms: number;
};

export type EntityDefinition = {
  name: string;
  format: EntityFormat;
  description: string;
  source: "model" | "derived";
};

export type Evaluation = {
  id: number;
  created_at: string;
  finished_at: string | null;
  dataset: string;
  model: string;
  status: "running" | "completed" | "partial" | "failed" | "cancelled";
  total_documents: number;
  completed_documents: number;
  error: string | null;
  max_pages: number;
  pipeline: string;
  provider: "lm_studio" | "gemini" | "none";
  steps: string[];
  execution_profile: ModelExecutionProfile | null;
  succeeded_documents: number;
  failed_documents: number;
  pending_documents: number;
  total_elapsed_ms: number;
  average_elapsed_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  ocr_pages: number;
  layout_pages: number;
  metrics: Metrics;
};

export type EvaluationDetail = {
  id: number;
  created_at: string;
  finished_at: string | null;
  dataset: string;
  model: string;
  status: "running" | "completed" | "partial" | "failed" | "cancelled";
  total_documents: number;
  completed_documents: number;
  error: string | null;
  max_pages: number;
  pipeline: string;
  provider: "lm_studio" | "gemini" | "none";
  steps: string[];
  execution_profile: ModelExecutionProfile | null;
  succeeded_documents: number;
  failed_documents: number;
  pending_documents: number;
  total_elapsed_ms: number;
  average_elapsed_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  ocr_pages: number;
  layout_pages: number;
  metrics: Metrics;
  prompts: PromptConfiguration;
  pipeline_definition: PipelineDefinition | null;
  documents: EvaluationDocumentResult[];
};

export type EvaluationDocumentResult = {
  name: string;
  status: string;
  error: string | null;
  elapsed_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  items: EvaluationFieldResult[];
};

export type EvaluationFieldResult = {
  entity: string;
  expected: string | number | boolean | null;
  actual: string | number | boolean | null;
  confidence: "low" | "medium" | "high";
  matched: boolean;
};

export type EvaluationRequest = {
  dataset: string;
};

export type ExtractionResponse = {
  document_type: string;
  run_id: number | null;
  filename: string;
  model: string;
  elapsed_ms: number;
  data: Record<string, FieldExtraction>;
  processing: ProcessingInfo;
  locations: FieldLocation[];
};

export type ExtractionRun = {
  id: number;
  created_at: string;
  filename: string;
  file_sha256: string;
  model: string;
  page_count: number;
  processed_pages: number;
  elapsed_ms: number;
  source: string;
  provider: string;
  pipeline: string;
  steps: string[];
  execution_profile: ModelExecutionProfile | null;
  has_corrections: boolean;
};

export type ExtractionRunDetail = {
  id: number;
  created_at: string;
  filename: string;
  file_sha256: string;
  model: string;
  page_count: number;
  processed_pages: number;
  elapsed_ms: number;
  source: string;
  provider: string;
  pipeline: string;
  steps: string[];
  execution_profile: ModelExecutionProfile | null;
  has_corrections: boolean;
  prompts: PromptConfiguration;
  extraction: Record<string, FieldExtraction>;
  corrections: Record<string, unknown>;
};

export type FieldExtraction = {
  value: string | number | null;
  confidence: "low" | "medium" | "high";
  warning: string | null;
  score: number | null;
};

export type FieldLocation = {
  entity: string;
  page: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
};

export type GcpKeyStatus = {
  configured: boolean;
  path: string;
  client_email: string;
  project_id: string;
  problem: string;
  verified_processors: string[];
};

export type GcpSettings = {
  project_id: string;
  location: string;
  ocr_processor_id: string;
  layout_processor_id: string;
  custom_extractor_processor_id: string;
  ocr_per_thousand_pages: number | null;
  layout_per_thousand_pages: number | null;
  pricing_checked_on: string;
};

export type GeminiKeyStatus = {
  configured: boolean;
  hint: string;
  verified_models: string[];
};

export type GeminiSettings = {
  api_key: string;
  thinking_level: "low" | "medium" | "high";
  pricing: Record<string, ModelPricing>;
  pricing_checked_on: string;
};

export type HealthStatus = {
  status: string;
  lm_studio: boolean;
  active_model: string;
  lm_studio_error: string | null;
};

export type LabelsRequest = {
  labels: Record<string, unknown>;
};

export type MasterDataColumn = {
  key: string;
  label: string;
  hint: string;
  kind: "identifier" | "text" | "timestamp";
  editable: boolean;
  generated: boolean;
};

export type MasterDataImport = {
  added: number;
  skipped: number;
  reasons: string[];
};

export type MasterDataRowRequest = {
  values: Record<string, string>;
};

export type MasterDataTable = {
  key: string;
  label: string;
  description: string;
  id_column: string;
  seed_entity: string;
  match_column: string;
  columns: MasterDataColumn[];
};

export type MetricTally = {
  matched: number;
  total: number;
  accuracy: number | null;
};

export type Metrics = {
  matched: number;
  total: number;
  accuracy: number | null;
  per_entity: Record<string, MetricTally>;
  per_confidence: Record<string, MetricTally>;
};

export type ModelExecutionProfile = {
  provider: "lm_studio" | "gemini";
  profile: "standard" | "compatibility" | "compatibility_partial" | "hosted";
  parameters: string | null;
  quantization: string | null;
  model_size_bytes: number | null;
  temperature: number;
  seed: number | null;
  reasoning_effort: string | null;
  thinking_level: string | null;
  context_length: number | null;
  parallel: number | null;
  eval_batch_size: number | null;
  flash_attention: boolean | null;
  offload_kv_cache_to_gpu: boolean | null;
};

export type ModelInfo = {
  id: string;
  name: string;
  provider: "lm_studio" | "gemini";
  parameters: string | null;
  quantization: string | null;
  size_bytes: number | null;
  context_length: number | null;
  parallel: number | null;
  requires_safe_profile: boolean;
  profile_matches: boolean;
  loaded: boolean;
  ready: boolean;
  capabilities_known: boolean;
  runtime_state: "not_loaded" | "loaded" | "loading" | "warming_up" | "ready" | "error" | "profile_mismatch";
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
  profile: "standard" | "compatibility" | "compatibility_partial";
  already_loaded: boolean;
  already_ready: boolean;
  warmup_mode: "vision" | "schema" | "vision_and_schema";
  preparation_attempts: number;
};

export type ModelPricing = {
  input_per_million: number | null;
  output_per_million: number | null;
};

export type PipelineDefinition = {
  name: string;
  description: string;
  page_limit: number;
  steps: PipelineStep[];
};

export type PipelineRenameRequest = {
  name: string;
};

export type PipelineStep = {
  kind: StepKind;
  config: Record<string, unknown>;
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

export type PromoteRunRequest = {
  run_ids: number[];
};

export type PromptConfiguration = {
  system_prompt: string;
  user_prompt: string;
  confidence_prompt: string;
  entities: EntityDefinition[];
};

export type PromptPreview = {
  provider: string;
  system_prompt: string;
  generation_schema: string;
  output_token_budget: number | null;
};

export type PromptPreviewRequest = {
  prompts: PromptConfiguration;
  provider: "lm_studio" | "gemini";
};

export type RuntimeEngineInfo = {
  engine: string | null;
  uses_gpu: boolean;
  accelerator: string | null;
  accelerator_bytes: number | null;
  accelerator_integrated: boolean;
  offload_budget_bytes: number | null;
};

export type SavedPipeline = {
  name: string;
  description: string;
  page_limit: number;
  steps: PipelineStep[];
  problems: string[];
  warnings: string[];
};

export type StepCatalogueEntry = {
  kind: string;
  label: string;
  description: string;
  requires_all: string[];
  requires_any: string[];
  produces: string[];
};

export type SupplierRuleModel = {
  id: number | null;
  id_subject: string;
  entity: string;
  kind: "fixed" | "regex" | "prompt";
  value: string;
  pattern: string;
  prompt: string;
  note: string;
};

export type SupplierRuleRequest = {
  id_subject: string;
  entity: string;
  kind: "fixed" | "regex" | "prompt";
  value: string;
  pattern: string;
  prompt: string;
  note: string;
};

export type SupplierRuleUpdate = {
  entity: string | null;
  kind: "fixed" | "regex" | "prompt" | null;
  value: string | null;
  pattern: string | null;
  prompt: string | null;
  note: string | null;
};
