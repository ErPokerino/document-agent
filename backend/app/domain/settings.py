"""What is configured: providers, prices, the Document AI catalog, and the app settings that hold them."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.extraction import PromptConfiguration
from app.pipeline.definition import DEFAULT_PIPELINE_NAME


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
        "gemini-3.8-flash": ModelPricing(input_per_million=0.75, output_per_million=3.75),
        # Pro has context-dependent tariffs; a flat rate must be configured explicitly.
        "gemini-3.1-pro-preview": ModelPricing(),
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


class DocumentProcessor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["document_ai_ocr", "document_ai_layout", "document_ai_extract"]
    project_id: str = Field(pattern=r"^[A-Za-z0-9-]+$")
    location: str = Field(pattern=r"^[a-z0-9-]+$")
    processor_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")


class ProcessorRecord(DocumentProcessor):
    used_by: list[str] = Field(default_factory=list)


class ProcessorVersion(BaseModel):
    id: str
    name: str
    state: str


class ProcessorInspection(BaseModel):
    display_name: str
    state: str
    default_version: str | None = None
    versions: list[ProcessorVersion] = Field(default_factory=list)
    checked_at: str


class GcpSettings(BaseModel):
    """Where Document AI lives and which processors to call.

    No credentials here: the key is a file on disk, and nothing about it is
    ever sent to the browser.
    """

    model_config = ConfigDict(extra="forbid")

    processors: list[DocumentProcessor] = Field(default_factory=list)
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
    custom_extractor_per_thousand_pages: Annotated[float | None, Field(ge=0)] = None
    pricing_checked_on: str = "2026-08-22"


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["lm_studio", "gemini", "model_server"] = "lm_studio"
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


class GeminiKeyStatus(BaseModel):
    configured: bool
    hint: str = ""
    verified_models: list[str] = Field(default_factory=list)


class GcpKeyStatus(BaseModel):
    """What the backend can say about the key file without revealing it."""

    configured: bool
    path: str
    client_email: str = ""
    project_id: str = ""
    problem: str = ""
    verified_processors: list[str] = Field(default_factory=list)
