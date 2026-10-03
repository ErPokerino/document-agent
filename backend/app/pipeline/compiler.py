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
    OCR_ONLY_WITHOUT_PDF_TEXT,
    contract_for,
    describe_problems,
    filled_entities,
    is_pdf_text_fallback,
)
from app.pipeline.regex_refine import RegexRule
from app.pipeline.steps import (
    ApplySupplierRules,
    ExtractWithCustomExtractor,
    ExtractEntities,
    InspectPdf,
    LookUpInMasterData,
    MarkUnfilledDerivedEntities,
    PredictWithArtifact,
    ReadPdfText,
    ReadWithDocumentAi,
    RefineWithRegex,
    RenderPages,
)
from app.services.master_data import TABLES, MasterDataStore, UnknownTable
from app.services.supplier_rules import SupplierRule, SupplierRuleStore
from app.services.similarity import ALGORITHMS, DEFAULT_ALGORITHM


DEFAULT_RENDER_SCALE = 1.35


class PipelineError(ValueError):
    """The pipeline cannot be run as written."""


class FrozenRegister:
    """The supplier rows a run started with, instead of the live table.

    A retry that looked up today's register would score a different experiment
    under the same run id. `rows` ignores the search arguments the live store
    accepts: the snapshot is already the whole table.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = [dict(row) for row in rows]

    def table(self, key: str):
        if key not in TABLES:
            raise UnknownTable(f"No reference table named {key!r}")
        return TABLES[key]

    def rows(self, table_key: str, **_: Any) -> list[dict[str, Any]]:
        self.table(table_key)
        return [dict(row) for row in self._rows]


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
    supplier_rules: SupplierRuleStore | None,
    register_rows: list[dict[str, Any]] | None,
    frozen_rules: list[SupplierRule] | None,
    artifacts: Any = None,
    ocr_follows: bool = False,
) -> Any:
    from app.services.processors import binding, KINDS
    config = binding(step, gcp) if step.kind.value in KINDS else step.config
    if step.kind is StepKind.render_pages:
        return RenderPages(scale=float(config.get("scale", DEFAULT_RENDER_SCALE)))
    if step.kind is StepKind.read_pdf_text:
        return ReadPdfText(feeds_model=bool(config.get("feeds_model", True)), ocr_follows=ocr_follows)
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
            project_id=config.get("project_id"), location=config.get("location"),
            only_without_pdf_text=(
                step.kind is StepKind.document_ai_ocr and bool(config.get(OCR_ONLY_WITHOUT_PDF_TEXT))
            ),
        )
    if step.kind is StepKind.llm_extract:
        return ExtractEntities(prompts)
    if step.kind is StepKind.regex_refine:
        return RefineWithRegex(entities, _rules(config))
    if step.kind is StepKind.document_ai_extract:
        return ExtractWithCustomExtractor(
            str(config.get("processor_id") or gcp.custom_extractor_processor_id),
            entities,
            project_id=config.get("project_id"), location=config.get("location"),
        )
    if step.kind is StepKind.supplier_rules:
        if frozen_rules is not None:
            applicable = frozen_rules
        elif supplier_rules is None:
            raise PipelineError("No supplier rules are available to apply")
        else:
            applicable = supplier_rules.all()
        return ApplySupplierRules(
            applicable,
            prompts,
            str(config.get("source_entity") or "id_subject"),
        )
    if step.kind is StepKind.master_data_lookup:
        if register_rows is not None:
            source = FrozenRegister(register_rows)
        elif master_data is None:
            raise PipelineError("No master data is available to look anything up in")
        else:
            source = master_data
        return LookUpInMasterData(
            entities=entities,
            master_data=source,
            table=_table(config),
            source_entity=_required_entity(config, "source_entity"),
            target_entity=_required_entity(config, "target_entity"),
            algorithm=_algorithm(config),
            minimum_similarity=_threshold(config),
        )
    if step.kind is StepKind.artifact_predict:
        return _predictor(config, entities, artifacts)
    raise PipelineError(f"No runnable step exists for '{step.kind.value}'")


def _predictor(config: dict[str, Any], entities: list[EntityDefinition], artifacts: Any) -> PredictWithArtifact:
    """A trained model, and the fields of it this step is to fill.

    The model is read here, so an artefact that was deleted or damaged stops
    the pipeline before the first document rather than on it.
    """
    from app.training.artifacts import InvalidArtifact, UnknownArtifact

    if artifacts is None:
        raise PipelineError("No trained models are available to predict with")
    identity = str(config.get("artifact_id") or "").strip()
    if not identity:
        raise ValueError("no trained model is chosen")
    try:
        stored = artifacts.get(identity)
        model = artifacts.load(identity)
    except (UnknownArtifact, InvalidArtifact) as exc:
        raise ValueError(str(exc)) from exc
    wanted = [str(name) for name in config.get("entities") or []]
    if not wanted:
        raise ValueError("no field is chosen for it to fill")
    learned = set(stored.manifest.get("entities") or [])
    unlearned = [name for name in wanted if name not in learned]
    if unlearned:
        raise ValueError(f"the model was not trained on: {', '.join(unlearned)}")
    by_name = {entity.name: entity for entity in entities}
    missing = [name for name in wanted if name not in by_name]
    if missing:
        raise ValueError(f"these fields are not configured in Extraction: {', '.join(missing)}")
    threshold = float(config.get("minimum_similarity", 0.0))
    if not 0 <= threshold <= 1:
        raise ValueError("the minimum similarity must be between 0 and 1")
    return PredictWithArtifact(
        model=model,
        entities=[by_name[name] for name in wanted],
        minimum_similarity=threshold,
        artifact_id=identity,
        artifact_name=str(stored.manifest.get("name") or identity),
    )


def build_steps(
    definition: PipelineDefinition,
    *,
    prompts: PromptConfiguration,
    entities: list[EntityDefinition],
    gcp: GcpSettings | None = None,
    master_data: MasterDataStore | None = None,
    supplier_rules: SupplierRuleStore | None = None,
    register_rows: list[dict[str, Any]] | None = None,
    frozen_rules: list[SupplierRule] | None = None,
    artifacts: Any = None,
) -> list[Any]:
    """The executable steps, with the PDF inspection the engine always needs first."""
    problems = describe_problems(definition)
    if problems:
        raise PipelineError(" ".join(problems))

    steps: list[Any] = [InspectPdf(page_limit=definition.page_limit)]
    for index, step in enumerate(definition.steps, start=1):
        try:
            steps.append(
                _build_one(
                    step,
                    prompts=prompts,
                    entities=entities,
                    gcp=gcp or GcpSettings(),
                    master_data=master_data,
                    supplier_rules=supplier_rules,
                    register_rows=register_rows,
                    frozen_rules=frozen_rules,
                    artifacts=artifacts,
                    # describe_problems has already refused a fallback with
                    # an extraction between it and this reader.
                    ocr_follows=any(is_pdf_text_fallback(later) for later in definition.steps[index:]),
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
