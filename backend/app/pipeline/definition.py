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
    read_pdf_text = "read_pdf_text"
    document_ai_ocr = "document_ai_ocr"
    document_ai_layout = "document_ai_layout"
    document_ai_extract = "document_ai_extract"
    llm_extract = "llm_extract"
    regex_refine = "regex_refine"
    master_data_lookup = "master_data_lookup"
    supplier_rules = "supplier_rules"
    artifact_predict = "artifact_predict"
    resolve_candidates = "resolve_candidates"


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
    StepKind.read_pdf_text: StepContract(
        kind=StepKind.read_pdf_text,
        label="Read PDF text",
        description=(
            "Read the text a native PDF already carries, with word positions, on "
            "this machine. A scan carries none, and the step says so rather than "
            "passing an empty reading on, unless a Document AI OCR step after it "
            "is set to read such a PDF."
        ),
        requires_all=(Artifact.pdf,),
        produces=(Artifact.text,),
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
    StepKind.document_ai_extract: StepContract(
        kind=StepKind.document_ai_extract,
        label="Document AI Custom Extractor",
        description=(
            "Read the configured fields with a Custom Extractor. It answers with "
            "values, its own confidence and the box each value sits in, so it "
            "replaces the model call rather than feeding it."
        ),
        requires_all=(),
        produces=(Artifact.entities, Artifact.text),
    ),
    StepKind.supplier_rules: StepContract(
        kind=StepKind.supplier_rules,
        label="Supplier rules",
        description=(
            "Apply the corrections written for whichever supplier this document "
            "turned out to be from. Needs the supplier to have been identified first."
        ),
        requires_all=(Artifact.entities,),
        produces=(Artifact.entities,),
    ),
    StepKind.artifact_predict: StepContract(
        kind=StepKind.artifact_predict,
        label="Trained model",
        description=(
            "Predict fields with a model trained in Models on labelled datasets, from "
            "the text a reading step left. Runs on this machine."
        ),
        requires_all=(Artifact.text,),
        produces=(Artifact.entities,),
    ),
    StepKind.resolve_candidates: StepContract(
        kind=StepKind.resolve_candidates,
        label="Resolve candidates",
        description=(
            "Choose each field's value among what the steps before it proposed: by "
            "priority between methods, by confidence, or by agreement. Without it, "
            "the last step to write a field decides."
        ),
        requires_all=(Artifact.entities,),
        produces=(Artifact.entities,),
    ),
}


def contract_for(kind: StepKind) -> StepContract:
    return CONTRACTS[kind]


# The OCR step setting that makes it read a document only when Read PDF text
# found none on it. Chosen in the pipeline rather than done automatically:
# sending a scan to Google is a decision about where documents go, and a
# pipeline that reads on this machine must not start uploading on its own.
OCR_ONLY_WITHOUT_PDF_TEXT = "only_without_pdf_text"


class PipelineStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: StepKind
    config: dict[str, Any] = Field(default_factory=dict)


def is_pdf_text_fallback(step: PipelineStep) -> bool:
    """An OCR step that reads only what Read PDF text found no text on."""
    return step.kind is StepKind.document_ai_ocr and bool(step.config.get(OCR_ONLY_WITHOUT_PDF_TEXT))


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


def uses_model(pipeline: PipelineDefinition) -> bool:
    """True when running this pipeline can call the selected language model.

    Not every pipeline does. One that extracts with the Custom Extractor never
    sends the document to a model at all, and making such a run wait until
    several gigabytes are loaded and warm is a delay that buys nothing.

    Supplier rules count, because one of them may be an instruction to ask the
    model again, and which supplier a document is from is not known until the
    run is under way.
    """
    return any(
        step.kind in (StepKind.llm_extract, StepKind.supplier_rules)
        for step in pipeline.steps
    )


def filled_entities(pipeline: PipelineDefinition) -> set[str]:
    """The entity names a step in this pipeline writes by itself."""
    filled: set[str] = set()
    for step in pipeline.steps:
        if step.kind is StepKind.master_data_lookup:
            target = str(step.config.get("target_entity") or "").strip()
            if target:
                filled.add(target)
        if step.kind is StepKind.artifact_predict:
            filled.update(str(name) for name in step.config.get("entities") or [])
    return filled


def describe_warnings(
    pipeline: PipelineDefinition,
    entities: "list | None" = None,
) -> list[str]:
    """What is worth knowing about this pipeline, without stopping it.

    A pipeline that fills only some of the derived entities is a legitimate
    thing to run — that is how one pipeline is compared with another that does
    more. It is not something to discover from a column of zeroes, either.
    """
    filled = filled_entities(pipeline)
    warnings = [
        f"This pipeline does not fill '{entity.name}'. It will come out empty, "
        f"and a test run will score it as missing on every document."
        for entity in entities or []
        if getattr(entity, "source", "model") == "derived" and entity.name not in filled
    ]
    # Measured on Test-Dataset, run 43: OCR left on "Every document" after
    # Read PDF text billed an OCR page for each of the nine native PDFs, and
    # the scan was refused at Read PDF text before the OCR was reached.
    reader = next(
        (index for index, step in enumerate(pipeline.steps, start=1) if step.kind is StepKind.read_pdf_text),
        None,
    )
    if reader is not None:
        label = contract_for(StepKind.document_ai_ocr).label
        warnings.extend(
            f"Step {index} ({label}) reads every document, including those Read PDF text "
            f"found text on, and a PDF without text is still refused at step {reader}."
            for index, step in enumerate(pipeline.steps, start=1)
            if index > reader and step.kind is StepKind.document_ai_ocr and not is_pdf_text_fallback(step)
        )
    return warnings


def _fallback_problems(steps: list[PipelineStep], index: int) -> list[str]:
    """Why an OCR step set to stand in for Read PDF text cannot do so.

    `index` is 1-based, as in every message. The OCR step needs a Read PDF text
    step before it to learn whether there was text, and nothing that fills
    entities may sit between the two: on a scan it would run with no text.
    """
    label = contract_for(StepKind.document_ai_ocr).label
    before = steps[: index - 1]
    readers = [position for position, step in enumerate(before, start=1) if step.kind is StepKind.read_pdf_text]
    if not readers:
        return [
            f"Step {index} ({label}) reads only a PDF without text of its own, "
            "and no Read PDF text step comes before it."
        ]
    return [
        f"Step {position} ({contract_for(step.kind).label}) comes between Read PDF text and "
        f"step {index} ({label}), so on a PDF without text it would run before the OCR."
        for position, step in enumerate(steps[readers[-1] : index - 1], start=readers[-1] + 1)
        if Artifact.entities in contract_for(step.kind).produces
    ]


def describe_problems(
    pipeline: PipelineDefinition,
    entities: "list | None" = None,
) -> list[str]:
    """Everything that stops this pipeline from running, in words someone can act on."""
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
        if is_pdf_text_fallback(step):
            problems.extend(_fallback_problems(pipeline.steps, index))

    if Artifact.entities not in available:
        problems.append("The pipeline produces no entities: nothing would come out of a run.")
    return problems
