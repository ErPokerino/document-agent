"""Models trained on the datasets: algorithms, features, jobs, the registry, and remote targets."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReadingCacheStatus(BaseModel):
    """How many Document AI readings are kept, and the room they take."""

    entries: int
    size_bytes: int


class KnnParameters(BaseModel):
    """How a nearest-neighbour model turns text into vectors, and how neighbours vote."""

    model_config = ConfigDict(extra="forbid")

    # Character n-grams within word boundaries tolerate OCR noise — a word
    # misread by one letter still shares most of its n-grams — where whole
    # words do not.
    analyzer: Literal["char_wb", "word"] = "char_wb"
    ngram_min: Annotated[int, Field(ge=1, le=8)] = 3
    ngram_max: Annotated[int, Field(ge=1, le=8)] = 5
    sublinear_tf: bool = True
    # A term in fewer documents than this is left out of the vocabulary.
    min_df: Annotated[int, Field(ge=1, le=100)] = 1
    # A term in more than this share of documents is left out: it says nothing
    # about which document this is.
    max_df: Annotated[float, Field(gt=0, le=1)] = 0.95
    max_features: Annotated[int | None, Field(ge=100, le=2_000_000)] = 200_000
    # How much of each document's text is compared, from its start.
    max_characters: Annotated[int, Field(ge=200, le=500_000)] = 20_000
    k: Annotated[int, Field(ge=1, le=25)] = 1
    weighting: Literal["distance", "uniform"] = "distance"

    @model_validator(mode="after")
    def ngram_range_is_ordered(self) -> "KnnParameters":
        if self.ngram_max < self.ngram_min:
            raise ValueError("The largest n-gram cannot be shorter than the smallest")
        return self


class TextFeatures(BaseModel):
    """How a document's text becomes numbers, for every algorithm that reads text."""

    model_config = ConfigDict(extra="forbid")

    analyzer: Literal["char_wb", "word"] = "char_wb"
    ngram_min: Annotated[int, Field(ge=1, le=8)] = 3
    ngram_max: Annotated[int, Field(ge=1, le=8)] = 5
    sublinear_tf: bool = True
    min_df: Annotated[int, Field(ge=1, le=100)] = 1
    max_df: Annotated[float, Field(gt=0, le=1)] = 0.95
    max_features: Annotated[int | None, Field(ge=100, le=2_000_000)] = 200_000
    max_characters: Annotated[int, Field(ge=200, le=500_000)] = 20_000
    # Truncated SVD to this many dimensions, or None to keep the sparse
    # TF-IDF. Trees split on single columns, and a few hundred dense
    # components suit them better than two hundred thousand sparse ones.
    reduce_to: Annotated[int | None, Field(ge=2, le=2000)] = None

    @model_validator(mode="after")
    def ngram_range_is_ordered(self) -> "TextFeatures":
        if self.ngram_max < self.ngram_min:
            raise ValueError("The largest n-gram cannot be shorter than the smallest")
        return self


class ParameterSpec(BaseModel):
    """One setting of an algorithm, described well enough for the UI to draw it."""

    name: str
    label: str
    kind: Literal["int", "float", "choice", "bool"]
    default: bool | int | float | str
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: list[str] = Field(default_factory=list)
    help: str = ""


class AlgorithmInfo(BaseModel):
    id: str
    label: str
    family: Literal["neighbours", "linear", "boosting", "foundation"]
    description: str
    # available: it can train here; not_installed: its package is missing;
    # not_connected: it runs on a service DocuFlow does not reach yet.
    status: Literal["available", "not_installed", "not_connected"]
    runs: Literal["local", "remote"] = "local"
    install: str | None = None
    # Whether it reads the text, and whether extracted fields can join it.
    reads_text: bool = True
    takes_fields: bool = False
    # The text reduction it is offered with, None for the sparse TF-IDF.
    default_reduce_to: int | None = None
    parameters: list[ParameterSpec] = Field(default_factory=list)


class TrainingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=80)]
    algorithm: Annotated[str, Field(min_length=1)] = "knn_tfidf"
    datasets: Annotated[list[str], Field(min_length=1)]
    pipeline: Annotated[str, Field(min_length=1)]
    entities: Annotated[list[str], Field(min_length=1)]
    # Other fields used as features beside the text, for algorithms that take
    # them. Learned from their labels; at run time read from what earlier
    # steps extracted.
    input_fields: list[str] = Field(default_factory=list)
    text: TextFeatures = Field(default_factory=TextFeatures)
    parameters: dict[str, bool | int | float | str] = Field(default_factory=dict)
    cutoff_entity: str | None = None
    cutoff_before: str | None = None


class TrainingJobModel(BaseModel):
    id: int
    kind: str
    name: str
    created_at: str
    status: Literal["running", "completed", "failed", "cancelled"]
    total: int
    done: int
    artifact_id: str | None = None
    error: str | None = None
    skipped: list[str] = Field(default_factory=list)
    output: str | None = None
    examples: int = 0
    phase: str | None = None


class FineTuningExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=80)]
    datasets: Annotated[list[str], Field(min_length=1)]
    pipeline: Annotated[str, Field(min_length=1)]
    format: Literal["vertex_gemini", "openai_chat"] = "vertex_gemini"


class ArtifactEntityValidation(BaseModel):
    documents: int
    accuracy: float | None = None
    macro_f1: float | None = None
    classes: int = 0


class ArtifactSummary(BaseModel):
    """A trained model as the registry keeps it."""

    id: str
    name: str
    kind: str
    algorithm: str = "knn_tfidf"
    algorithm_label: str = "Nearest neighbour"
    family: str | None = None
    input_fields: list[str] = Field(default_factory=list)
    features: str = ""
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    # False when the algorithm it was trained with cannot run on this machine.
    runnable: bool = True
    created_at: str
    entities: list[str]
    input: str = "text"
    parameters: dict[str, Any] = Field(default_factory=dict)
    libraries: dict[str, str] = Field(default_factory=dict)
    datasets: list[str] = Field(default_factory=list)
    pipeline: str | None = None
    reader: list[str] = Field(default_factory=list)
    documents: int = 0
    cutoff_entity: str | None = None
    cutoff_before: str | None = None
    excluded_by_cutoff: int = 0
    unreadable: int = 0
    validation_method: str | None = None
    validation: dict[str, ArtifactEntityValidation] = Field(default_factory=dict)
    imported: bool = False
    size_bytes: int
    used_by: list[str] = Field(default_factory=list)


class TrainingProvider(BaseModel):
    """A place a model can be trained that DocuFlow names but does not reach yet."""

    id: str
    name: str
    platform: str
    trains: str
    status: Literal["available", "not_connected"]
    description: str
