"""What a pipeline is, and whether a given one can work.

Every step declares what it needs and what it leaves behind. That is enough to
tell someone their pipeline is broken while they are composing it, instead of
letting it fail on the third document of a run.

The artifacts are deliberately coarse. A step does not care whether the text it
reads came from an OCR processor or a layout parser, only that text is there,
which is what makes the pieces interchangeable.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")

# The pipeline every install starts from, and what a run recorded before
# pipelines existed must have used.
DEFAULT_PIPELINE_NAME = "Vision extraction"


class Artifact(str, Enum):
    pdf = "pdf"
    images = "images"
    text = "text"
    layout = "layout"
    entities = "entities"


class StepKind(str, Enum):
    render_pages = "render_pages"
    document_ai_ocr = "document_ai_ocr"
    document_ai_layout = "document_ai_layout"
    llm_extract = "llm_extract"
    regex_refine = "regex_refine"
    master_data_lookup = "master_data_lookup"


@dataclass(frozen=True)
class StepContract:
    kind: StepKind
    label: str
    description: str
    requires_all: tuple[Artifact, ...] = ()
    # At least one of these. Extraction reads page images or text, either will do.
    requires_any: tuple[Artifact, ...] = ()
    produces: tuple[Artifact, ...] = ()


CONTRACTS: dict[StepKind, StepContract] = {
    StepKind.render_pages: StepContract(
        kind=StepKind.render_pages,
        label="Render pages",
        description="Turn the first pages of the PDF into images for a vision model.",
        requires_all=(Artifact.pdf,),
        produces=(Artifact.images,),
    ),
    StepKind.document_ai_ocr: StepContract(
        kind=StepKind.document_ai_ocr,
        label="Document AI OCR",
        description="Read the page text with Google's OCR processor, including scans.",
        requires_all=(Artifact.pdf,),
        produces=(Artifact.text,),
    ),
    StepKind.document_ai_layout: StepContract(
        kind=StepKind.document_ai_layout,
        label="Document AI Layout Parser",
        description="Read the text and keep the headings, tables and lists around it.",
        requires_all=(Artifact.pdf,),
        produces=(Artifact.text, Artifact.layout),
    ),
    StepKind.llm_extract: StepContract(
        kind=StepKind.llm_extract,
        label="LLM extraction",
        description="Ask a model for the configured entities, constrained to the schema.",
        requires_any=(Artifact.images, Artifact.text),
        produces=(Artifact.entities,),
    ),
    StepKind.regex_refine: StepContract(
        kind=StepKind.regex_refine,
        label="Regex refinement",
        description="Rewrite or fill single fields with rules you control.",
        requires_all=(Artifact.entities,),
        produces=(Artifact.entities,),
    ),
    StepKind.master_data_lookup: StepContract(
        kind=StepKind.master_data_lookup,
        label="Master data lookup",
        description="Fill a field the document never carried, by matching a name to the register.",
        requires_all=(Artifact.entities,),
        produces=(Artifact.entities,),
    ),
}


def contract_for(kind: StepKind) -> StepContract:
    return CONTRACTS[kind]


class PipelineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: StepKind
    config: dict[str, Any] = Field(default_factory=dict)


class PipelineDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    # How many of the first pages this pipeline looks at. It belongs to the
    # pipeline, not to the app: an OCR pipeline and a vision pipeline pay very
    # different prices per page and rarely want the same number.
    page_limit: Annotated[int, Field(ge=1, le=100)] = 10
    steps: list[PipelineStep] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def name_is_usable_as_a_file_name(cls, value: str) -> str:
        if not SAFE_NAME.match(value) or value.strip() != value:
            raise ValueError("A pipeline name must be plain text without path separators")
        return value

    @staticmethod
    def default() -> "PipelineDefinition":
        """Exactly what the app did before pipelines existed."""
        return PipelineDefinition(
            name=DEFAULT_PIPELINE_NAME,
            description="Render the first pages and send them to a vision model in one call.",
            steps=[
                PipelineStep(kind=StepKind.render_pages, config={"scale": 1.35}),
                PipelineStep(kind=StepKind.llm_extract, config={}),
            ],
        )


def requires_vision(pipeline: PipelineDefinition) -> bool:
    """True when a model in this pipeline is handed page images.

    A pipeline that reads OCR text can use a text-only model, so this is what
    decides whether a model without vision may be selected.
    """
    available: set[Artifact] = {Artifact.pdf}
    for step in pipeline.steps:
        if step.kind is StepKind.llm_extract and Artifact.images in available:
            return True
        available.update(contract_for(step.kind).produces)
    return False


def filled_entities(pipeline: PipelineDefinition) -> set[str]:
    """The entity names a step in this pipeline writes by itself."""
    filled: set[str] = set()
    for step in pipeline.steps:
        if step.kind is StepKind.master_data_lookup:
            target = str(step.config.get("target_entity") or "").strip()
            if target:
                filled.add(target)
    return filled


def describe_problems(
    pipeline: PipelineDefinition,
    entities: "list | None" = None,
) -> list[str]:
    """Everything wrong with this pipeline, in words someone can act on.

    `entities` is optional so the shape of a pipeline can be checked on its
    own. Given it, the check also covers the other half of the contract: a
    derived entity nobody fills would be scored as wrong on every document.
    """
    if not pipeline.steps:
        return ["The pipeline is empty: add at least a step that produces entities."]

    problems: list[str] = []
    available: set[Artifact] = {Artifact.pdf}

    for index, step in enumerate(pipeline.steps, start=1):
        contract = contract_for(step.kind)
        missing = [artifact.value for artifact in contract.requires_all if artifact not in available]
        if missing:
            problems.append(
                f"Step {index} ({contract.label}) needs {' and '.join(missing)}, "
                "and nothing before it produces that."
            )
        if contract.requires_any and not any(
            artifact in available for artifact in contract.requires_any
        ):
            options = " or ".join(artifact.value for artifact in contract.requires_any)
            problems.append(
                f"Step {index} ({contract.label}) needs {options}, "
                "and nothing before it produces either."
            )
        available.update(contract.produces)

    if Artifact.entities not in available:
        problems.append("The pipeline produces no entities: nothing would come out of a run.")

    filled = filled_entities(pipeline)
    for entity in entities or []:
        if getattr(entity, "source", "model") == "derived" and entity.name not in filled:
            problems.append(
                f"Nothing in this pipeline fills '{entity.name}', which is a derived entity. "
                "Add the step that produces it, or it will be empty on every document."
            )
    return problems
