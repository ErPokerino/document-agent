"""Ground truth: datasets, labels, and the Workspace runs that can become labels."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.extraction import PromptConfiguration, FieldExtraction
from app.domain.runtime import ModelExecutionProfile


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


class LabelValue(BaseModel):
    value: str
    documents: int


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
