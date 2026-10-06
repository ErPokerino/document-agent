"""What is configured: providers, prices, the Document AI catalog, and the app settings that hold them."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    """A starting rate for each hosted model that can be selected.

    Paid tier, checked on 2026-08-21. Verify against the pricing page. A
    retired model gets none: it cannot be chosen, and a rate for it is kept
    only where an installation already had one, for the cost of its old runs.
    """
    return {
        "gemini-3.8-flash": ModelPricing(input_per_million=0.75, output_per_million=3.75),
        # Pro has context-dependent tariffs; a flat rate must be configured explicitly.
        "gemini-3.1-pro-preview": ModelPricing(),
        "gemini-3.5-flash-lite": ModelPricing(input_per_million=0.30, output_per_million=2.50),
    }


class GeminiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Write-only over HTTP: the API masks it on the way out.
    api_key: str = ""
    thinking_level: Literal["low", "medium", "high"] = "low"
    # Through Vertex AI only. None is the deployment's location; a preview
    # model may be offered in `global` alone.
    location: Literal["eu", "us", "global"] | None = None
    pricing: dict[str, ModelPricing] = Field(default_factory=default_gemini_pricing)
    pricing_checked_on: str = "2026-08-21"
    # Models whose default rate has been offered once. A default is added to
    # an installation only the first time, so a rate someone removed stays
    # removed instead of coming back on the next read.
    pricing_defaults_offered: list[str] = Field(default_factory=lambda: list(default_gemini_pricing()))


class ModelGardenSettings(BaseModel):
    """Partner endpoints and generation controls; credentials come from GCP."""

    model_config = ConfigDict(extra="forbid")
    claude_location: Literal["eu", "us", "global"] = "eu"
    grok_location: Literal["us", "global"] = "global"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    claude_max_output_tokens: Annotated[int, Field(ge=256, le=10000)] = 4096
    grok_max_output_tokens: Annotated[int, Field(ge=256, le=10000)] = 4096

    @model_validator(mode="before")
    @classmethod
    def _per_publisher_limit(cls, data: Any) -> Any:
        """Settings saved before each publisher had its own limit hold one shared value."""
        if isinstance(data, dict) and "max_output_tokens" in data:
            data = dict(data)
            shared = data.pop("max_output_tokens")
            data.setdefault("claude_max_output_tokens", shared)
            data.setdefault("grok_max_output_tokens", shared)
        return data

    def output_limit(self, publisher: str | None) -> int:
        return self.claude_max_output_tokens if publisher == "anthropic" else self.grok_max_output_tokens


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

    provider: Literal["lm_studio", "gemini", "model_server", "model_garden"] = "lm_studio"
    # No default: which models exist is a property of the machine DocuFlow
    # was installed on, and naming one here opens a fresh install already
    # configured for a model the user does not have.
    model: str = ""
    excluded_model_ids: list[str] = Field(default_factory=list)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    model_garden: ModelGardenSettings = Field(default_factory=ModelGardenSettings)
    gcp: GcpSettings = Field(default_factory=GcpSettings)
    lm_studio_url: str = "http://127.0.0.1:1234"
    pipeline: str = DEFAULT_PIPELINE_NAME
    theme: Literal["system", "light", "dark"] = "system"
    prompts: PromptConfiguration = Field(default_factory=PromptConfiguration)


class HostedModelCheck(BaseModel):
    """What one hosted model answered to a one-token request, in one location."""

    model: str
    publisher: str
    location: str
    # answering: it replied. no_quota: Google refused it with 429 (the
    # project has no quota left, none at all, or a shared quota was busy). not_offered: 404, the model
    # does not exist in that location. refused: any other refusal.
    status: Literal["answering", "no_quota", "not_offered", "refused"]
    detail: str = ""
    checked_at: str


class PartnerTariff(BaseModel):
    """The recorded Model Garden rate for one model in one location, USD per million tokens."""

    model: str
    location: str
    input: float | None = None
    output: float | None = None
    cache_read: float | None = None
    cache_write_5m: float | None = None
    cache_write_1h: float | None = None
    checked_on: str
    source: str


class HostedVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publisher: Literal["google", "anthropic", "xai"]
    location: Literal["eu", "us", "global"]


class GeminiKeyStatus(BaseModel):
    configured: bool
    hint: str = ""
    verified_models: list[str] = Field(default_factory=list)
    # "vertex": the deployment reaches Gemini through Vertex AI as its own
    # identity, in `vertex_location`; no key is used or needed.
    access: Literal["api_key", "vertex"] = "api_key"
    vertex_location: str | None = None
    # The deployment's own location, used while none is chosen in LLM.
    deployment_location: str | None = None


class GcpKeyStatus(BaseModel):
    """What the backend can say about the key file without revealing it."""

    # "runtime_identity": the deployment calls Google as its own service
    # account, named in `client_email`; there is no key file.
    access: Literal["key_file", "runtime_identity"] = "key_file"

    configured: bool
    path: str
    client_email: str = ""
    project_id: str = ""
    problem: str = ""
    verified_processors: list[str] = Field(default_factory=list)
