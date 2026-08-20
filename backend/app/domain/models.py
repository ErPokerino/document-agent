from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_SYSTEM_PROMPT = """You are an information extraction agent specialized in invoices.
Analyze only the content visible in the supplied pages.
Never invent values or use knowledge that is not present in the document.
Return null when a value is missing or unreadable.
"""

DEFAULT_USER_PROMPT = """Extract the configured entities from invoice pages {page_range}.
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


class ModelInfo(BaseModel):
    id: str
    name: str
    parameters: str | None = None
    quantization: str | None = None
    size_bytes: int | None = None
    context_length: int | None = None
    loaded: bool = False
    ready: bool = False
    runtime_state: Literal[
        "not_loaded", "loaded", "loading", "warming_up", "ready", "error"
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
    profile: Literal["default", "compatibility"]
    already_loaded: bool = False
    already_ready: bool = False
    warmup_mode: Literal["vision", "vision_and_schema"]
    preparation_attempts: int = 0


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "qwen/qwen3.8-27b"
    excluded_model_ids: list[str] = Field(default_factory=list)
    lm_studio_url: str = "http://127.0.0.1:1234"
    max_pages_to_analyze: Annotated[int, Field(ge=1, le=100)] = 10
    prompts: PromptConfiguration = Field(default_factory=PromptConfiguration)


class HealthStatus(BaseModel):
    status: str
    lm_studio: bool
    active_model: str


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


class ExtractionResponse(BaseModel):
    document_type: str = "invoice"
    run_id: int | None = None
    filename: str
    model: str
    elapsed_ms: int
    data: dict[str, FieldExtraction]
    processing: ProcessingInfo


# --- Prompt Lab -------------------------------------------------------------


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
    status: Literal["running", "completed", "failed", "cancelled"]
    total_documents: int
    completed_documents: int
    error: str | None = None
    max_pages: int
    total_elapsed_ms: int
    average_elapsed_ms: int | None = None
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
    items: list[EvaluationFieldResult]


class EvaluationDetail(Evaluation):
    prompts: PromptConfiguration
    documents: list[EvaluationDocumentResult]
