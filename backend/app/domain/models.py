from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.pipeline.definition import DEFAULT_PIPELINE_NAME, PipelineDefinition, PipelineStep


DEFAULT_SYSTEM_PROMPT = """You are an information extraction agent specialized in invoices.
Analyze only the content visible in the supplied pages.
Never invent values or use knowledge that is not present in the document.
Return null when a value is missing or unreadable.
"""

DEFAULT_USER_PROMPT = """Extract the configured entities from the invoice, page {page_range} of it.
Check the header, tax summary and final payable amount carefully.
Return only the requested JSON object.
"""

DEFAULT_CONFIDENCE_PROMPT = """Assign a qualitative confidence level to every extracted field:
- high: the value is clearly visible, explicitly labelled and unambiguous;
- medium: the value is readable but identified through context or has minor ambiguity;
- low: the value is partial, hard to read, conflicting or unavailable.
When value is null, confidence must be low. Confidence is a qualitative assessment, not a probability.
"""


class EntityFormat(str, Enum):
    text = "text"
    date = "date"
    currency = "currency"
    decimal = "decimal"
    integer = "integer"


class EntityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64)]
    format: EntityFormat
    description: Annotated[str, Field(min_length=1, max_length=800)]
    # Where the value comes from. A derived entity is never asked of the model:
    # it is worked out from the others, or from the document text, by a step in
    # the pipeline. It is still labelled and scored like any other field.
    source: Literal["model", "derived"] = "model"


def model_entities(entities: list["EntityDefinition"]) -> list["EntityDefinition"]:
    """The ones the model is asked for, in order."""
    return [entity for entity in entities if entity.source == "model"]


def derived_entities(entities: list["EntityDefinition"]) -> list["EntityDefinition"]:
    """The ones a pipeline step has to fill, in order."""
    return [entity for entity in entities if entity.source == "derived"]


def default_entities() -> list[EntityDefinition]:
    return [
        EntityDefinition(
            name="date",
            format=EntityFormat.date,
            description="Invoice issue date, not the due date. Normalize it to YYYY-MM-DD.",
        ),
        EntityDefinition(
            name="document_number",
            format=EntityFormat.text,
            description="Invoice identifier exactly as printed in the document.",
        ),
        EntityDefinition(
            name="supplier_name",
            format=EntityFormat.text,
            description="The seller that created the invoice. Prefer the company beside the logo, directly under the invoice title, or in the remittance section. Ignore any company in the bill-to/address block and never return the account, customer, recipient or attention name.",
        ),
        EntityDefinition(
            name="currency",
            format=EntityFormat.currency,
            description="Currency of the final total as an ISO 4217 code, for example EUR, USD or GBP.",
        ),
        EntityDefinition(
            name="total_amount",
            format=EntityFormat.decimal,
            description="Final invoice total including taxes, as a positive number without symbols or thousands separators.",
        ),
    ]


class PromptConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: Annotated[str, Field(min_length=1, max_length=8000)] = DEFAULT_SYSTEM_PROMPT
    user_prompt: Annotated[str, Field(min_length=1, max_length=4000)] = DEFAULT_USER_PROMPT
    confidence_prompt: Annotated[str, Field(min_length=1, max_length=4000)] = DEFAULT_CONFIDENCE_PROMPT
    entities: Annotated[list[EntityDefinition], Field(min_length=1, max_length=40)] = Field(
        default_factory=default_entities
    )

    @model_validator(mode="after")
    def entity_names_are_unique(self) -> "PromptConfiguration":
        names = [entity.name for entity in self.entities]
        if len(names) != len(set(names)):
            raise ValueError("Entity names must be unique")
        return self


class FieldExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | float | int | None
    confidence: Literal["low", "medium", "high"]
    warning: str | None = None
    # Only a step that computes a number sets this: a lookup reports how close
    # the match was. `confidence` stays the level everything else reads, so a
    # derived field is scored and filtered exactly like any other.
    score: float | None = None


class RuntimeEngineInfo(BaseModel):
    """Which llama.cpp build LM Studio will run a local model on, and on what.

    `--gpu off` holds a model's own layers on the processor but leaves the
    vision projector on whatever this engine targets, so a GPU build and a
    CPU-safe load are not the same thing.

    The accelerator and the budget are reported because they decide how every
    model here is loaded. On a machine DocuFlow has never seen, that decision
    is the thing worth being able to check.
    """

    engine: str | None = None
    uses_gpu: bool = False
    accelerator: str | None = None
    accelerator_bytes: int | None = None
    accelerator_integrated: bool = False
    # How much model this host will be trusted to hold. Zero means every model
    # is loaded on the processor; null means the machine could not be read.
    offload_budget_bytes: int | None = None


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: Literal["lm_studio", "gemini"] = "lm_studio"
    parameters: str | None = None
    quantization: str | None = None
    size_bytes: int | None = None
    context_length: int | None = None
    parallel: int | None = None
    # A large or IQ-quantized model offloaded to this machine's integrated GPU
    # loses the Vulkan device, so those are loaded with `--gpu off`. That covers
    # the model's layers only; see RuntimeEngineInfo for what it does not.
    requires_safe_profile: bool = False
    # False when the loaded instance was not the one we prepared: LM Studio
    # loads on demand with its own defaults, and that instance crashes here.
    profile_matches: bool = True
    loaded: bool = False
    ready: bool = False
    # False when the model was found through the OpenAI-compatible endpoint,
    # which reports ids and nothing else. `vision` is then not a claim that
    # the model cannot see, only that nothing here knows whether it can.
    capabilities_known: bool = True
    runtime_state: Literal[
        "not_loaded", "loaded", "loading", "warming_up", "ready", "error", "profile_mismatch"
    ] = "not_loaded"
    vision: bool = True


class ModelLoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Annotated[str, Field(min_length=1, max_length=500)]


class ModelLoadResponse(BaseModel):
    model: str
    status: Literal["ready"] = "ready"
    load_ms: int
    warmup_ms: int
    total_ms: int
    unloaded_models: int
    # "compatibility_partial" is the CPU-safe profile minus the one part
    # only the LM Studio CLI can set: holding the layers off the GPU.
    profile: Literal["standard", "compatibility", "compatibility_partial"]
    already_loaded: bool = False
    already_ready: bool = False
    warmup_mode: Literal["vision", "schema", "vision_and_schema"]
    preparation_attempts: int = 0


class ModelPricing(BaseModel):
    """USD per million tokens. Editable, because published prices change.

    Gemini 3.7 Flash is already scheduled to double on 1 January 2027, so a
    hardcoded constant would quietly start lying. Cost is derived from these at
    display time and never stored on a run: update a rate and history follows.
    """

    model_config = ConfigDict(extra="forbid")

    input_per_million: float | None = None
    output_per_million: float | None = None


def default_gemini_pricing() -> dict[str, ModelPricing]:
    # Paid tier, checked on 2026-08-21. Verify against the pricing page.
    return {
        "gemini-3.7-flash": ModelPricing(input_per_million=0.75, output_per_million=3.75),
        "gemini-3.5-flash-lite": ModelPricing(input_per_million=0.30, output_per_million=2.50),
    }


class GeminiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Write-only over HTTP: the API masks it on the way out.
    api_key: str = ""
    thinking_level: Literal["low", "medium", "high"] = "low"
    pricing: dict[str, ModelPricing] = Field(default_factory=default_gemini_pricing)
    pricing_checked_on: str = "2026-08-21"


class GcpSettings(BaseModel):
    """Where Document AI lives and which processors to call.

    No credentials here: the key is a file on disk, and nothing about it is
    ever sent to the browser.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = ""
    location: str = "eu"
    ocr_processor_id: str = ""
    layout_processor_id: str = ""
    # A Custom Extractor reads the fields itself, so it replaces the model
    # call rather than feeding it.
    custom_extractor_processor_id: str = ""
    # USD per 1000 pages, editable for the same reason the Gemini rates are.
    ocr_per_thousand_pages: float | None = 1.5
    layout_per_thousand_pages: float | None = 10.0
    pricing_checked_on: str = "2026-08-22"


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["lm_studio", "gemini"] = "lm_studio"
    # No default: which models exist is a property of the machine DocuFlow
    # was installed on, and naming one here opens a fresh install already
    # configured for a model the user does not have.
    model: str = ""
    excluded_model_ids: list[str] = Field(default_factory=list)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    gcp: GcpSettings = Field(default_factory=GcpSettings)
    lm_studio_url: str = "http://127.0.0.1:1234"
    pipeline: str = DEFAULT_PIPELINE_NAME
    theme: Literal["system", "light", "dark"] = "system"
    prompts: PromptConfiguration = Field(default_factory=PromptConfiguration)


class ModelExecutionProfile(BaseModel):
    """The provider settings that can change an otherwise identical run."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["lm_studio", "gemini"]
    profile: Literal["standard", "compatibility", "compatibility_partial", "hosted"]
    parameters: str | None = None
    quantization: str | None = None
    model_size_bytes: int | None = None
    temperature: float = 0
    seed: int | None = None
    reasoning_effort: str | None = None
    thinking_level: str | None = None
    context_length: int | None = None
    parallel: int | None = None
    eval_batch_size: int | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None


class PromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompts: PromptConfiguration
    provider: Literal["lm_studio", "gemini"] = "lm_studio"


class PromptPreview(BaseModel):
    provider: str
    system_prompt: str
    generation_schema: str
    output_token_budget: int | None = None


class GeminiKeyStatus(BaseModel):
    configured: bool
    hint: str = ""
    verified_models: list[str] = Field(default_factory=list)


class SupplierRuleModel(BaseModel):
    """A correction written for one supplier's documents.

    Keyed on the register id, never the name: several spellings of one supplier
    resolve to the same id, and the id is what is either right or wrong.
    """

    id: int | None = None
    id_subject: str
    entity: str
    kind: Literal["fixed", "regex", "prompt"]
    value: str = ""
    pattern: str = ""
    prompt: str = ""
    note: str = ""


class SupplierRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_subject: str
    entity: str
    kind: Literal["fixed", "regex", "prompt"]
    value: str = ""
    pattern: str = ""
    prompt: str = ""
    note: str = ""


class SupplierRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str | None = None
    kind: Literal["fixed", "regex", "prompt"] | None = None
    value: str | None = None
    pattern: str | None = None
    prompt: str | None = None
    note: str | None = None


class MasterDataImport(BaseModel):
    """What an import did, row by row where it did not."""

    added: int
    skipped: int
    reasons: list[str] = Field(default_factory=list)


class HealthStatus(BaseModel):
    status: str
    lm_studio: bool
    active_model: str
    # Why the local models are missing, when they are. /api/models answers with
    # the hosted ones alone rather than failing outright, which is right — and
    # left nobody with a reason for the empty half of the list.
    lm_studio_error: str | None = None


class ProcessingInfo(BaseModel):
    page_count: int
    processed_pages: int
    first_processed_page: int = 1
    last_processed_page: int
    cut_applied: bool
    single_call_page_limit: int
    configured_page_limit: int
    time_to_first_token_seconds: float | None = None
    prediction_time_seconds: float | None = None
    tokens_per_second: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class FieldLocation(BaseModel):
    """Where on the page a value was found, for highlighting it.

    Coordinates are normalized 0-1 across the page, so they hold at whatever
    size the page is rendered. Absent for a field the OCR never showed — and
    absent entirely when no pipeline step read the page with OCR.
    """

    entity: str
    page: int
    left: float
    top: float
    right: float
    bottom: float


class ExtractionResponse(BaseModel):
    document_type: str = "invoice"
    run_id: int | None = None
    filename: str
    model: str
    elapsed_ms: int
    data: dict[str, FieldExtraction]
    processing: ProcessingInfo
    locations: list[FieldLocation] = Field(default_factory=list)


# --- datasets, master data and evaluation runs -------------------------------------------------------------


class Dataset(BaseModel):
    name: str
    document_count: int
    labelled_count: int


class DatasetDocument(BaseModel):
    name: str
    size_bytes: int
    labelled: bool
    labelled_entities: list[str]
    label_source: str | None = None
    label_error: str | None = None


class DatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=128)]


class LabelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: dict[str, Any]


class DocumentLabels(BaseModel):
    document: str
    source: str
    labels: dict[str, Any]
    updated_at: str | None = None


class PromoteRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_ids: Annotated[list[int], Field(min_length=1, max_length=200)]


class ExtractionRun(BaseModel):
    id: int
    created_at: str
    filename: str
    file_sha256: str
    model: str
    page_count: int
    processed_pages: int
    elapsed_ms: int
    source: str
    provider: str
    pipeline: str
    steps: list[str] = Field(default_factory=list)
    execution_profile: ModelExecutionProfile | None = None
    has_corrections: bool


class ExtractionRunDetail(ExtractionRun):
    prompts: PromptConfiguration
    extraction: dict[str, FieldExtraction]
    corrections: dict[str, Any]


class CorrectionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrections: dict[str, Any]


class DraftLabels(BaseModel):
    document: str
    labels: dict[str, Any]
    confidence: dict[str, str]
    elapsed_ms: int


class MetricTally(BaseModel):
    matched: int
    total: int
    accuracy: float | None = None


class Metrics(BaseModel):
    matched: int
    total: int
    accuracy: float | None = None
    per_entity: dict[str, MetricTally] = Field(default_factory=dict)
    per_confidence: dict[str, MetricTally] = Field(default_factory=dict)


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: Annotated[str, Field(min_length=1, max_length=128)]


class Evaluation(BaseModel):
    id: int
    created_at: str
    finished_at: str | None = None
    dataset: str
    model: str
    status: Literal["running", "completed", "partial", "failed", "cancelled"]
    total_documents: int
    completed_documents: int
    error: str | None = None
    max_pages: int
    pipeline: str
    # Where the model ran, or `none` when this pipeline called no model. It
    # cannot be recovered from the selected model id afterwards.
    provider: Literal["lm_studio", "gemini", "none"] = "lm_studio"
    steps: list[str] = Field(default_factory=list)
    execution_profile: ModelExecutionProfile | None = None
    succeeded_documents: int
    failed_documents: int
    pending_documents: int
    total_elapsed_ms: int
    average_elapsed_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ocr_pages: int = 0
    layout_pages: int = 0
    metrics: Metrics


class EvaluationFieldResult(BaseModel):
    entity: str
    expected: str | float | int | bool | None
    actual: str | float | int | bool | None
    confidence: Literal["low", "medium", "high"]
    matched: bool


class EvaluationDocumentResult(BaseModel):
    name: str
    status: str
    error: str | None = None
    elapsed_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    items: list[EvaluationFieldResult]


class EvaluationDetail(Evaluation):
    prompts: PromptConfiguration
    pipeline_definition: PipelineDefinition | None = None
    documents: list[EvaluationDocumentResult]


class PipelineRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=64)]


class StepCatalogueEntry(BaseModel):
    kind: str
    label: str
    description: str
    requires_all: list[str]
    requires_any: list[str]
    produces: list[str]


class SavedPipeline(BaseModel):
    name: str
    description: str
    page_limit: int
    steps: list[PipelineStep]
    # Empty when the pipeline can run. The UI shows these instead of letting
    # someone start a run that would fail on the first document.
    problems: list[str] = Field(default_factory=list)
    # Worth knowing, but not a reason to refuse: a pipeline that fills only
    # some of the derived entities is a legitimate thing to run and compare.
    warnings: list[str] = Field(default_factory=list)


class GcpKeyStatus(BaseModel):
    """What the backend can say about the key file without revealing it."""

    configured: bool
    path: str
    client_email: str = ""
    project_id: str = ""
    problem: str = ""
    verified_processors: list[str] = Field(default_factory=list)


class MasterDataColumn(BaseModel):
    key: str
    label: str
    hint: str
    kind: Literal["identifier", "text", "timestamp"]
    editable: bool
    # Filled in automatically when a row is created; still editable afterwards.
    generated: bool = False


class MasterDataTable(BaseModel):
    key: str
    label: str
    description: str
    id_column: str
    seed_entity: str
    match_column: str
    columns: list[MasterDataColumn]


class MasterDataRowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, str]
