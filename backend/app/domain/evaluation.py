"""Lab runs and experiments: what was scored, how well, and how methods and cells compare."""

from typing import Annotated, Literal

from app.domain.billing import CostSummary

from pydantic import BaseModel, ConfigDict, Field

from app.domain.extraction import PromptConfiguration, FieldCandidate
from app.domain.runtime import ModelExecutionProfile
from app.pipeline.definition import PipelineDefinition, PipelineStep


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
    # Off by default: a Lab run measures what the pipeline costs in time and
    # pages, and a reused reading costs neither.
    reuse_readings: bool = False


class ExtractorProcessor(BaseModel):
    project_id: str | None = None
    location: str | None = None
    processor_id: str
    display_name: str | None = None
    version: str | None = None
    base_model: str | None = None


class ExtractionEngine(ExtractorProcessor):
    additional_processors: list[ExtractorProcessor] = Field(default_factory=list)


class Evaluation(BaseModel):
    processor_bindings: list[PipelineStep] = Field(default_factory=list)
    extraction_engine: ExtractionEngine | None = None
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
    provider: Literal["lm_studio", "gemini", "model_server", "model_garden", "none"] = "lm_studio"
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
    custom_extractor_pages: int | None = None
    usage_complete: bool = False
    cost: CostSummary | None = None
    # Null when the run was recorded before a fingerprint was computed.
    fingerprint: str | None = None
    # The pipeline step in flight while status is running. Empty once the
    # document that was being scored has finished.
    current_step: str | None = None
    # Whether Document AI readings stored by earlier runs were reused, and how
    # many pages were read back rather than sent. Neither is in the time or
    # the page counts above.
    reuse_readings: bool = False
    cached_pages: int = 0
    # The experiment this run is a cell of, and which cell.
    experiment_id: int | None = None
    experiment_cell: int | None = None
    metrics: Metrics


class EvaluationFieldResult(BaseModel):
    entity: str
    expected: str | float | int | bool | None
    actual: str | float | int | bool | None
    confidence: Literal["low", "medium", "high"]
    matched: bool
    score: float | None = None
    candidates: list[FieldCandidate] | None = None


class MethodScore(BaseModel):
    method: str
    documents: int
    answered: int
    correct: int
    accuracy: float | None = None


class FieldMethods(BaseModel):
    """One field: how each method did, how the chosen value did, and the ceiling."""

    entity: str
    documents: int
    resolved_accuracy: float | None = None
    # Share of documents where at least one method proposed the right value.
    oracle_accuracy: float | None = None
    methods: list[MethodScore]


class ResolutionTrial(BaseModel):
    """A stored run resolved again under another strategy."""

    matched: int
    total: int
    accuracy: float | None = None
    per_entity: dict[str, MetricTally]


class ClassScoreResult(BaseModel):
    label: str
    support: int
    predicted: int
    true_positive: int
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None


class CoveragePointResult(BaseModel):
    threshold: float
    answered: int
    coverage: float
    accuracy: float


class ClassificationResult(BaseModel):
    """One categorical field, scored as a classifier rather than a string."""

    entity: str
    documents: int
    accuracy: float | None = None
    macro_f1: float | None = None
    classes: list[ClassScoreResult]
    labels: list[str]
    confusion: list[list[int]]
    ranked_by: Literal["score", "confidence", "none"]
    coverage: list[CoveragePointResult]


class EvaluationDocumentResult(BaseModel):
    name: str
    status: str
    error: str | None = None
    elapsed_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # The CSV carried these per document while the detail dropped them.
    ocr_pages: int | None = None
    layout_pages: int | None = None
    custom_extractor_pages: int | None = None
    cached_pages: int | None = None
    items: list[EvaluationFieldResult]


class PipelineActivity(BaseModel):
    """The step a document request is inside, while that request is open."""

    step: str | None = None


class EvaluationDetail(Evaluation):
    prompts: PromptConfiguration
    pipeline_definition: PipelineDefinition | None = None
    has_dataset_snapshot: bool = False
    # False on a run that did not record the register and the supplier rules.
    # A retry of that run uses whatever those tables hold today.
    has_register_snapshot: bool = False
    documents: list[EvaluationDocumentResult]
    # One per categorical field the run scored.
    classification: list[ClassificationResult] = Field(default_factory=list)
    # One per field that recorded candidates. Empty on runs from before them.
    methods: list[FieldMethods] = Field(default_factory=list)


class ExperimentModelChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["lm_studio", "gemini", "model_server", "model_garden"]
    model: Annotated[str, Field(min_length=1)]


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(max_length=80)] = ""
    dataset: Annotated[str, Field(min_length=1, max_length=128)]
    pipelines: Annotated[list[str], Field(min_length=1, max_length=20)]
    # Ignored by a pipeline that calls no model; it is one cell whatever is chosen.
    models: Annotated[list[ExperimentModelChoice], Field(max_length=12)] = Field(default_factory=list)
    reuse_readings: bool = False


class ExperimentCell(BaseModel):
    index: int
    pipeline: str
    provider: Literal["lm_studio", "gemini", "model_server", "model_garden", "none"]
    model: str
    # pending, loading, running, completed, partial, failed, cancelled, skipped, error
    status: str
    skipped: str | None = None
    error: str | None = None
    run: Evaluation | None = None


class ExperimentCellScore(BaseModel):
    cell: int
    accuracy: float
    low: float
    high: float
    delta: float
    delta_low: float
    delta_high: float
    verdict: Literal["best", "worse", "indistinguishable"]
    seconds_per_document: float | None = None
    per_entity: dict[str, float | None] = Field(default_factory=dict)


class ExperimentComparison(BaseModel):
    """Every finished cell, scored on the documents all of them scored."""

    shared_documents: list[str]
    left_out: list[str]
    resamples: int
    cells: list[ExperimentCellScore]


class Experiment(BaseModel):
    id: int
    name: str
    created_at: str
    finished_at: str | None = None
    dataset: str
    status: Literal["running", "completed", "cancelled", "failed"]
    reuse_readings: bool
    error: str | None = None
    cells: list[ExperimentCell]
    comparison: ExperimentComparison | None = None
