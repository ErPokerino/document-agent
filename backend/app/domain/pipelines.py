"""Saved pipelines as the API shows them."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.pipeline.definition import PipelineStep


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
