"""What a document is asked for and what comes back: fields, prompts, values, candidates."""

from enum import Enum
from typing import Annotated, Any, Literal

from app.domain.billing import CostSummary

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    # One value out of a set of classes: a document type, a cost centre, a
    # supplier id. The set may be written down (closed) or left to whatever
    # the labelled documents say (open), which is what a nearest-neighbour
    # prediction needs: it can only answer with a class it has seen.
    category = "category"


# A closed vocabulary sent to a model becomes an enum in its grammar, and every
# label is one more branch in it. Large enough for a register of suppliers.
MAX_CATEGORIES = 1000


MAX_CATEGORY_LENGTH = 200


def category_key(value: Any) -> str:
    """What two spellings of one class have in common: case and spacing aside."""
    return " ".join(str(value).split()).casefold()


class EntityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64)]
    format: EntityFormat
    description: Annotated[str, Field(min_length=1, max_length=800)]
    # Where the value comes from. A derived entity is never asked of the model:
    # it is worked out from the others, or from the document text, by a step in
    # the pipeline. It is still labelled and scored like any other field.
    source: Literal["model", "derived"] = "model"
    # Only for a category. Empty means open: the classes are whatever the
    # labelled documents say, and anything well formed is accepted.
    categories: Annotated[list[str], Field(max_length=MAX_CATEGORIES)] = Field(default_factory=list)

    @field_validator("categories")
    @classmethod
    def categories_are_distinct_labels(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(label.split()) for label in value]
        if any(not label for label in cleaned):
            raise ValueError("A category cannot be empty")
        if any(len(label) > MAX_CATEGORY_LENGTH for label in cleaned):
            raise ValueError(f"A category can be at most {MAX_CATEGORY_LENGTH} characters long")
        keys = [category_key(label) for label in cleaned]
        if len(keys) != len(set(keys)):
            raise ValueError("Two categories differ only in case or spacing")
        return cleaned

    @model_validator(mode="after")
    def only_a_category_has_categories(self) -> "EntityDefinition":
        if self.categories and self.format is not EntityFormat.category:
            raise ValueError(f"'{self.name}' is not a category, so it cannot list categories")
        return self


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


class FieldCandidate(BaseModel):
    """One method's proposal for a field, kept beside the value that was chosen."""

    model_config = ConfigDict(extra="forbid")

    # The step that proposed it: its kind, or the trained model it used.
    method: str
    value: str | float | int | None
    confidence: Literal["low", "medium", "high"]
    score: float | None = None
    warning: str | None = None
    evidence: str | None = None


class FieldExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | float | int | None
    confidence: Literal["low", "medium", "high"]
    warning: str | None = None
    # Only a step that computes a number sets this: a lookup reports how close
    # the match was. `confidence` stays the level everything else reads, so a
    # derived field is scored and filtered exactly like any other.
    score: float | None = None
    # What the value rests on, when a step can say: the labelled document a
    # nearest-neighbour model took it from, and how close that document was.
    evidence: str | None = None
    # Every value a step proposed for this field, in the order the steps ran.
    # The value above is the last of them unless a Resolve step chose another.
    candidates: list[FieldCandidate] = Field(default_factory=list)


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
    cost: CostSummary | None = None
    filename: str
    model: str
    elapsed_ms: int
    data: dict[str, FieldExtraction]
    processing: ProcessingInfo
    locations: list[FieldLocation] = Field(default_factory=list)


class PromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompts: PromptConfiguration
    provider: Literal["lm_studio", "gemini", "model_server", "model_garden"] = "lm_studio"


class PromptPreview(BaseModel):
    provider: str
    system_prompt: str
    generation_schema: str
    output_token_budget: int | None = None
