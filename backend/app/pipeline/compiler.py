"""Turn a saved pipeline definition into steps the engine can run.

Everything that can be refused is refused here, before a single document is
opened: a run that dies on document seven because a regex never compiled is a
worse experience than one that never starts.
"""

from typing import Any

from pydantic import ValidationError

from app.domain.models import EntityDefinition, GcpSettings, PromptConfiguration
from app.pipeline.definition import (
    PipelineDefinition,
    PipelineStep,
    StepKind,
    contract_for,
    describe_problems,
    filled_entities,
)
from app.pipeline.regex_refine import RegexRule
from app.pipeline.steps import (
    ExtractEntities,
    InspectPdf,
    LookUpInMasterData,
    MarkUnfilledDerivedEntities,
    ReadWithDocumentAi,
    RefineWithRegex,
    RenderPages,
)
from app.services.master_data import TABLES, MasterDataStore
from app.services.similarity import ALGORITHMS, DEFAULT_ALGORITHM


DEFAULT_RENDER_SCALE = 1.35


class PipelineError(ValueError):
    """The pipeline cannot be run as written."""


def _rules(config: dict[str, Any]) -> list[RegexRule]:
    return [RegexRule.model_validate(rule) for rule in config.get("rules", [])]


def _required_entity(config: dict[str, Any], key: str) -> str:
    name = str(config.get(key) or "").strip()
    if not name:
        raise ValueError(f"no {key.replace('_', ' ')} is chosen")
    return name


def _table(config: dict[str, Any]) -> str:
    table = str(config.get("table") or "suppliers")
    if table not in TABLES:
        raise ValueError(f"{table!r} is not one of: {', '.join(TABLES)}")
    return table


def _algorithm(config: dict[str, Any]) -> str:
    algorithm = str(config.get("algorithm") or DEFAULT_ALGORITHM)
    if algorithm not in ALGORITHMS:
        raise ValueError(f"{algorithm!r} is not one of: {', '.join(ALGORITHMS)}")
    return algorithm


def _threshold(config: dict[str, Any]) -> float:
    value = float(config.get("minimum_similarity", 0.75))
    if not 0 <= value <= 1:
        raise ValueError("the minimum similarity must be between 0 and 1")
    return value


def _build_one(
    step: PipelineStep,
    *,
    prompts: PromptConfiguration,
    entities: list[EntityDefinition],
    gcp: GcpSettings,
    master_data: MasterDataStore | None,
) -> Any:
    config = step.config
    if step.kind is StepKind.render_pages:
        return RenderPages(scale=float(config.get("scale", DEFAULT_RENDER_SCALE)))
    if step.kind in (StepKind.document_ai_ocr, StepKind.document_ai_layout):
        # The processor comes from Settings unless the step names its own,
        # which is how a second processor can be tried without changing both.
        configured = (
            gcp.ocr_processor_id
            if step.kind is StepKind.document_ai_ocr
            else gcp.layout_processor_id
        )
        return ReadWithDocumentAi(
            step.kind.value,
            str(config.get("processor_id") or configured),
            # Default on: an OCR step that was added before this flag
            # existed was added to give the model text.
            feeds_model=bool(config.get("feeds_model", True)),
        )
    if step.kind is StepKind.llm_extract:
        return ExtractEntities(prompts)
    if step.kind is StepKind.regex_refine:
        return RefineWithRegex(entities, _rules(config))
    if step.kind is StepKind.master_data_lookup:
        if master_data is None:
            raise PipelineError("No master data is available to look anything up in")
        return LookUpInMasterData(
            entities=entities,
            master_data=master_data,
            table=_table(config),
            source_entity=_required_entity(config, "source_entity"),
            target_entity=_required_entity(config, "target_entity"),
            algorithm=_algorithm(config),
            minimum_similarity=_threshold(config),
        )
    raise PipelineError(f"No runnable step exists for '{step.kind.value}'")


def build_steps(
    definition: PipelineDefinition,
    *,
    prompts: PromptConfiguration,
    entities: list[EntityDefinition],
    gcp: GcpSettings | None = None,
    master_data: MasterDataStore | None = None,
    max_pages: int | None = None,
) -> list[Any]:
    """The executable steps, with the PDF inspection the engine always needs first."""
    problems = describe_problems(definition)
    if problems:
        raise PipelineError(" ".join(problems))

    steps: list[Any] = [
        InspectPdf(max_pages_to_analyze=definition.page_limit, max_pages=max_pages)
    ]
    for index, step in enumerate(definition.steps, start=1):
        try:
            steps.append(
                _build_one(
                    step,
                    prompts=prompts,
                    entities=entities,
                    gcp=gcp or GcpSettings(),
                    master_data=master_data,
                )
            )
        except (ValidationError, ValueError) as exc:
            label = contract_for(step.kind).label
            raise PipelineError(f"Step {index} ({label}) is not usable: {exc}") from exc

    # Whatever no step fills is stated as empty, with the reason, rather than
    # quietly missing from the result.
    filled = filled_entities(definition)
    unfilled = [
        entity.name
        for entity in entities
        if entity.source == "derived" and entity.name not in filled
    ]
    if unfilled:
        steps.append(MarkUnfilledDerivedEntities(unfilled))
    return steps
