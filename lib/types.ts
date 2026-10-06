// Generated from the FastAPI OpenAPI schema. Do not edit by hand.
// Regenerate with: .venv/Scripts/python.exe backend/scripts/generate_types.py
//
// Every property is emitted as required: FastAPI serializes response models in
// full, defaults included, and the frontend always sends complete objects back.

export type EntityFormat = "text" | "date" | "currency" | "decimal" | "integer" | "category";

export type StepKind = "render_pages" | "read_pdf_text" | "document_ai_ocr" | "document_ai_layout" | "document_ai_extract" | "llm_extract" | "regex_refine" | "master_data_lookup" | "supplier_rules" | "artifact_predict" | "resolve_candidates";

export type Confidence = FieldExtraction["confidence"];

export type ModelRuntimeState = ModelInfo["runtime_state"];

export type AlgorithmInfo = {
  id: string;
  label: string;
  family: "neighbours" | "linear" | "boosting" | "foundation";
  description: string;
  status: "available" | "not_installed" | "not_connected";
  runs: "local" | "remote";
  install: string | null;
  reads_text: boolean;
  takes_fields: boolean;
  default_reduce_to: number | null;
  parameters: ParameterSpec[];
};

export type AppSettings = {
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden";
  model: string;
  excluded_model_ids: string[];
  gemini: GeminiSettings;
  model_garden: ModelGardenSettings;
  gcp: GcpSettings;
  lm_studio_url: string;
  pipeline: string;
  theme: "system" | "light" | "dark";
  prompts: PromptConfiguration;
};

export type ArtifactEntityValidation = {
  documents: number;
  accuracy: number | null;
  macro_f1: number | null;
  classes: number;
};

export type ArtifactSummary = {
  id: string;
  name: string;
  kind: string;
  algorithm: string;
  algorithm_label: string;
  family: string | null;
  input_fields: string[];
  features: string;
  hyperparameters: Record<string, unknown>;
  runnable: boolean;
  created_at: string;
  entities: string[];
  input: string;
  parameters: Record<string, unknown>;
  libraries: Record<string, string>;
  datasets: string[];
  pipeline: string | null;
  reader: string[];
  documents: number;
  cutoff_entity: string | null;
  cutoff_before: string | null;
  excluded_by_cutoff: number;
  unreadable: number;
  validation_method: string | null;
  validation: Record<string, ArtifactEntityValidation>;
  imported: boolean;
  size_bytes: number;
  used_by: string[];
};

export type ClassScoreResult = {
  label: string;
  support: number;
  predicted: number;
  true_positive: number;
  precision: number | null;
  recall: number | null;
  f1: number | null;
};

export type ClassificationResult = {
  entity: string;
  documents: number;
  accuracy: number | null;
  macro_f1: number | null;
  classes: ClassScoreResult[];
  labels: string[];
  confusion: number[][];
  ranked_by: "score" | "confidence" | "none";
  coverage: CoveragePointResult[];
};

export type CorrectionsRequest = {
  corrections: Record<string, unknown>;
};

export type CostSummary = {
  status: "complete" | "partial" | "unknown";
  currency: "USD";
  total_usd: number | null;
  known_usd: number;
  calls: number;
  source: string | null;
  checked_on: string | null;
};

export type CoveragePointResult = {
  threshold: number;
  answered: number;
  coverage: number;
  accuracy: number;
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

export type DocumentProcessor = {
  id: string;
  name: string;
  kind: "document_ai_ocr" | "document_ai_layout" | "document_ai_extract";
  project_id: string;
  location: string;
  processor_id: string;
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
  categories: string[];
};

export type Evaluation = {
  processor_bindings: PipelineStep[];
  extraction_engine: ExtractionEngine | null;
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
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden" | "none";
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
  custom_extractor_pages: number | null;
  usage_complete: boolean;
  cost: CostSummary | null;
  fingerprint: string | null;
  current_step: string | null;
  reuse_readings: boolean;
  cached_pages: number;
  experiment_id: number | null;
  experiment_cell: number | null;
  metrics: Metrics;
};

export type EvaluationDetail = {
  processor_bindings: PipelineStep[];
  extraction_engine: ExtractionEngine | null;
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
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden" | "none";
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
  custom_extractor_pages: number | null;
  usage_complete: boolean;
  cost: CostSummary | null;
  fingerprint: string | null;
  current_step: string | null;
  reuse_readings: boolean;
  cached_pages: number;
  experiment_id: number | null;
  experiment_cell: number | null;
  metrics: Metrics;
  prompts: PromptConfiguration;
  pipeline_definition: PipelineDefinition | null;
  has_dataset_snapshot: boolean;
  has_register_snapshot: boolean;
  documents: EvaluationDocumentResult[];
  classification: ClassificationResult[];
  methods: FieldMethods[];
};

export type EvaluationDocumentResult = {
  name: string;
  status: string;
  error: string | null;
  elapsed_ms: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  ocr_pages: number | null;
  layout_pages: number | null;
  custom_extractor_pages: number | null;
  cached_pages: number | null;
  items: EvaluationFieldResult[];
};

export type EvaluationFieldResult = {
  entity: string;
  expected: string | number | boolean | null;
  actual: string | number | boolean | null;
  confidence: "low" | "medium" | "high";
  matched: boolean;
  score: number | null;
  candidates: FieldCandidate[] | null;
};

export type EvaluationRequest = {
  dataset: string;
  reuse_readings: boolean;
};

export type Experiment = {
  id: number;
  name: string;
  created_at: string;
  finished_at: string | null;
  dataset: string;
  status: "running" | "completed" | "cancelled" | "failed";
  reuse_readings: boolean;
  error: string | null;
  cells: ExperimentCell[];
  comparison: ExperimentComparison | null;
};

export type ExperimentCell = {
  index: number;
  pipeline: string;
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden" | "none";
  model: string;
  status: string;
  skipped: string | null;
  error: string | null;
  run: Evaluation | null;
};

export type ExperimentCellScore = {
  cell: number;
  accuracy: number;
  low: number;
  high: number;
  delta: number;
  delta_low: number;
  delta_high: number;
  verdict: "best" | "worse" | "indistinguishable";
  seconds_per_document: number | null;
  per_entity: Record<string, number | null>;
};

export type ExperimentComparison = {
  shared_documents: string[];
  left_out: string[];
  resamples: number;
  cells: ExperimentCellScore[];
};

export type ExperimentModelChoice = {
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden";
  model: string;
};

export type ExperimentRequest = {
  name: string;
  dataset: string;
  pipelines: string[];
  models: ExperimentModelChoice[];
  reuse_readings: boolean;
};

export type ExtractionEngine = {
  project_id: string | null;
  location: string | null;
  processor_id: string;
  display_name: string | null;
  version: string | null;
  base_model: string | null;
  additional_processors: ExtractorProcessor[];
};

export type ExtractionResponse = {
  document_type: string;
  run_id: number | null;
  cost: CostSummary | null;
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
  cost: CostSummary | null;
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
  cost: CostSummary | null;
  prompts: PromptConfiguration;
  extraction: Record<string, FieldExtraction>;
  corrections: Record<string, unknown>;
};

export type ExtractorProcessor = {
  project_id: string | null;
  location: string | null;
  processor_id: string;
  display_name: string | null;
  version: string | null;
  base_model: string | null;
};

export type FieldCandidate = {
  method: string;
  value: string | number | null;
  confidence: "low" | "medium" | "high";
  score: number | null;
  warning: string | null;
  evidence: string | null;
};

export type FieldExtraction = {
  value: string | number | null;
  confidence: "low" | "medium" | "high";
  warning: string | null;
  score: number | null;
  evidence: string | null;
  candidates: FieldCandidate[];
};

export type FieldLocation = {
  entity: string;
  page: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
};

export type FieldMethods = {
  entity: string;
  documents: number;
  resolved_accuracy: number | null;
  oracle_accuracy: number | null;
  methods: MethodScore[];
};

export type FieldRule = {
  strategy: "last" | "priority" | "best_confidence" | "agreement";
  priority: string[];
  minimum_score: number | null;
};

export type FineTuningExportRequest = {
  name: string;
  datasets: string[];
  pipeline: string;
  format: "vertex_gemini" | "openai_chat";
};

export type GcpKeyStatus = {
  access: "key_file" | "runtime_identity";
  configured: boolean;
  path: string;
  client_email: string;
  project_id: string;
  problem: string;
  verified_processors: string[];
};

export type GcpSettings = {
  processors: DocumentProcessor[];
  project_id: string;
  location: string;
  ocr_processor_id: string;
  layout_processor_id: string;
  custom_extractor_processor_id: string;
  ocr_per_thousand_pages: number | null;
  layout_per_thousand_pages: number | null;
  custom_extractor_per_thousand_pages: number | null;
  pricing_checked_on: string;
};

export type GeminiKeyStatus = {
  configured: boolean;
  hint: string;
  verified_models: string[];
  access: "api_key" | "vertex";
  vertex_location: string | null;
};

export type GeminiSettings = {
  api_key: string;
  thinking_level: "low" | "medium" | "high";
  pricing: Record<string, ModelPricing>;
  pricing_checked_on: string;
  pricing_defaults_offered: string[];
};

export type HealthStatus = {
  status: string;
  lm_studio: boolean;
  lm_studio_enabled: boolean;
  model_server: boolean;
  active_model: string;
  lm_studio_error: string | null;
};

export type LabelValue = {
  value: string;
  documents: number;
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

export type MethodScore = {
  method: string;
  documents: number;
  answered: number;
  correct: number;
  accuracy: number | null;
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
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden";
  profile: "standard" | "compatibility" | "compatibility_partial" | "hosted" | "server";
  parameters: string | null;
  quantization: string | null;
  model_size_bytes: number | null;
  temperature: number | null;
  seed: number | null;
  reasoning_effort: string | null;
  thinking_level: string | null;
  context_length: number | null;
  parallel: number | null;
  eval_batch_size: number | null;
  flash_attention: boolean | null;
  offload_kv_cache_to_gpu: boolean | null;
  project: string | null;
  location: string | null;
  publisher: string | null;
  max_output_tokens: number | null;
};

export type ModelGardenSettings = {
  claude_location: "eu" | "us" | "global";
  grok_location: "us" | "global";
  effort: "low" | "medium" | "high" | "xhigh" | "max";
  max_output_tokens: number;
};

export type ModelInfo = {
  id: string;
  name: string;
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden";
  publisher: string | null;
  location: string | null;
  preview: boolean;
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
  profile: "standard" | "compatibility" | "compatibility_partial" | "server";
  already_loaded: boolean;
  already_ready: boolean;
  warmup_mode: "vision" | "schema" | "vision_and_schema";
  preparation_attempts: number;
};

export type ModelPricing = {
  input_per_million: number | null;
  output_per_million: number | null;
};

export type ParameterSpec = {
  name: string;
  label: string;
  kind: "int" | "float" | "choice" | "bool";
  default: boolean | number | string;
  minimum: number | null;
  maximum: number | null;
  step: number | null;
  choices: string[];
  help: string;
};

export type PipelineActivity = {
  step: string | null;
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

export type ProcessorInspection = {
  display_name: string;
  state: string;
  default_version: string | null;
  versions: ProcessorVersion[];
  checked_at: string;
};

export type ProcessorRecord = {
  id: string;
  name: string;
  kind: "document_ai_ocr" | "document_ai_layout" | "document_ai_extract";
  project_id: string;
  location: string;
  processor_id: string;
  used_by: string[];
};

export type ProcessorVersion = {
  id: string;
  name: string;
  state: string;
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
  provider: "lm_studio" | "gemini" | "model_server" | "model_garden";
};

export type ReadingCacheStatus = {
  entries: number;
  size_bytes: number;
};

export type ResolutionConfig = {
  default: FieldRule;
  fields: Record<string, FieldRule>;
};

export type ResolutionTrial = {
  matched: number;
  total: number;
  accuracy: number | null;
  per_entity: Record<string, MetricTally>;
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

export type Session = {
  required: boolean;
  user: string | null;
};

export type SignIn = {
  username: string;
  password: string;
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

export type TextFeatures = {
  analyzer: "char_wb" | "word";
  ngram_min: number;
  ngram_max: number;
  sublinear_tf: boolean;
  min_df: number;
  max_df: number;
  max_features: number | null;
  max_characters: number;
  reduce_to: number | null;
};

export type TrainingJobModel = {
  id: number;
  kind: string;
  name: string;
  created_at: string;
  status: "running" | "completed" | "failed" | "cancelled";
  total: number;
  done: number;
  artifact_id: string | null;
  error: string | null;
  skipped: string[];
  output: string | null;
  examples: number;
  phase: string | null;
};

export type TrainingProvider = {
  id: string;
  name: string;
  platform: string;
  trains: string;
  status: "available" | "not_connected";
  description: string;
};

export type TrainingRequest = {
  name: string;
  algorithm: string;
  datasets: string[];
  pipeline: string;
  entities: string[];
  input_fields: string[];
  text: TextFeatures;
  parameters: Record<string, boolean | number | string>;
  cutoff_entity: string | null;
  cutoff_before: string | null;
};

export type UsageDetail = {
  cost: CostSummary;
  records: UsageRecord[];
};

export type UsageRecord = {
  id: string;
  group_id: string;
  created_at: string;
  model: string;
  provider: string;
  publisher: string | null;
  project: string | null;
  location: string | null;
  step: string;
  document: string;
  evaluation_id: number | null;
  run_id: number | null;
  status: string;
  http_status: number | null;
  request_id: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number;
  cache_write_5m_tokens: number;
  cache_write_1h_tokens: number;
  reasoning_tokens: number | null;
  raw_usage: Record<string, unknown>;
  tariff: Record<string, unknown>;
  cost: CostSummary;
};
