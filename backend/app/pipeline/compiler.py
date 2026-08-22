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
)
from app.pipeline.regex_refine import RegexRule
from app.pipeline.steps import (
    ExtractEntities,
    InspectPdf,
    ReadWithDocumentAi,
    RefineWithRegex,
    RenderPages,
)


DEFAULT_RENDER_SCALE = 1.35


class PipelineError(ValueError):
    """The pipeline cannot be run as written."""


def _rules(config: dict[str, Any]) -> list[RegexRule]:
    return [RegexRule.model_validate(rule) for rule in config.get("rules", [])]


def _build_one(
    step: PipelineStep,
    *,
    prompts: PromptConfiguration,
    entities: list[EntityDefinition],
    gcp: GcpSettings,
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
        return ReadWithDocumentAi(step.kind.value, str(config.get("processor_id") or configured))
    if step.kind is StepKind.llm_extract:
        return ExtractEntities(prompts)
    if step.kind is StepKind.regex_refine:
        return RefineWithRegex(entities, _rules(config))
    raise PipelineError(f"No runnable step exists for '{step.kind.value}'")


def build_steps(
    definition: PipelineDefinition,
    *,
    prompts: PromptConfiguration,
    entities: list[EntityDefinition],
    gcp: GcpSettings | None = None,
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
                )
            )
        except (ValidationError, ValueError) as exc:
            label = contract_for(step.kind).label
            raise PipelineError(f"Step {index} ({label}) is not usable: {exc}") from exc
    return steps
