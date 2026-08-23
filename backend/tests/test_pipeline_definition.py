import pytest
from pydantic import ValidationError

from app.domain.models import EntityDefinition, EntityFormat

from app.pipeline.definition import (
    Artifact,
    PipelineDefinition,
    PipelineStep,
    StepKind,
    contract_for,
    describe_problems,
    describe_warnings,
    requires_vision,
)


def render(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.render_pages, config={"max_pages": 1, "scale": 1.35, **config})


def extract(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.llm_extract, config={"provider": "gemini", "model": "gemini-3.7-flash", **config})


def regex(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.regex_refine, config={"rules": [], **config})


def pipeline(*steps: PipelineStep, name: str = "test", **extra) -> PipelineDefinition:
    return PipelineDefinition(name=name, steps=list(steps), **extra)


def test_the_document_itself_is_what_a_pipeline_starts_from() -> None:
    assert contract_for(StepKind.render_pages).requires_all == (Artifact.pdf,)


def test_rendering_then_extracting_is_a_valid_pipeline() -> None:
    assert describe_problems(pipeline(render(), extract())) == []


def test_extracting_with_nothing_to_look_at_is_reported() -> None:
    problems = describe_problems(pipeline(extract()))

    assert len(problems) == 1
    # The message has to name the step and what is missing, not just fail.
    assert "1" in problems[0]
    assert "images" in problems[0] and "text" in problems[0]


def test_a_pipeline_that_never_produces_entities_is_reported() -> None:
    problems = describe_problems(pipeline(render()))

    assert any("no entities" in problem.lower() for problem in problems)


def test_refining_before_anything_extracted_is_reported() -> None:
    problems = describe_problems(pipeline(render(), regex(), extract()))

    assert any("entities" in problem for problem in problems)


def test_refining_after_extraction_is_valid() -> None:
    assert describe_problems(pipeline(render(), extract(), regex())) == []


def test_an_empty_pipeline_is_reported() -> None:
    problems = describe_problems(pipeline())

    assert problems and "empty" in problems[0].lower()


def test_text_alone_satisfies_the_extraction_step() -> None:
    # This is what the OCR step will produce, and why llm_extract takes either.
    contract = contract_for(StepKind.llm_extract)

    assert Artifact.images in contract.requires_any
    assert Artifact.text in contract.requires_any


def test_every_step_kind_has_a_contract_and_a_label() -> None:
    for kind in StepKind:
        contract = contract_for(kind)
        assert contract.label
        assert contract.produces


def test_the_default_pipeline_reproduces_todays_behaviour() -> None:
    default = PipelineDefinition.default()

    assert [step.kind for step in default.steps] == [StepKind.render_pages, StepKind.llm_extract]
    assert describe_problems(default) == []


def test_a_pipeline_round_trips_through_plain_data() -> None:
    original = pipeline(render(max_pages=3), extract(), regex(), name="ocr-then-llm")

    restored = PipelineDefinition.model_validate(original.model_dump(mode="json"))

    assert restored == original
    assert restored.steps[0].config["max_pages"] == 3


def test_a_step_kind_that_does_not_exist_is_refused() -> None:
    with pytest.raises(ValueError):
        PipelineDefinition.model_validate({"name": "x", "steps": [{"kind": "teleport", "config": {}}]})


def test_a_pipeline_name_must_be_usable_as_a_file_name() -> None:
    with pytest.raises(ValueError):
        PipelineDefinition(name="../escape", steps=[render(), extract()])


def test_a_pipeline_carries_its_own_page_limit() -> None:
    assert PipelineDefinition.default().page_limit == 10
    assert pipeline(render(), extract(), page_limit=3).page_limit == 3


def test_a_page_limit_outside_what_a_single_call_can_hold_is_refused() -> None:
    for refused in (0, 101):
        with pytest.raises(ValidationError):
            pipeline(render(), extract(), page_limit=refused)


def test_a_pipeline_that_sends_images_to_the_model_needs_a_vision_model() -> None:
    assert requires_vision(PipelineDefinition.default()) is True


def test_a_pipeline_that_only_sends_text_does_not_need_a_vision_model() -> None:
    text_only = pipeline(
        PipelineStep(kind=StepKind.llm_extract),
        name="text-only",
    )
    # Nothing produces images before the model call, so a text model is enough.
    assert requires_vision(text_only) is False


def ocr(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.document_ai_ocr, config=config)


def layout(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.document_ai_layout, config=config)


def test_ocr_reads_the_pdf_and_leaves_text_behind() -> None:
    contract = contract_for(StepKind.document_ai_ocr)

    assert contract.requires_all == (Artifact.pdf,)
    assert contract.produces == (Artifact.text,)


def test_the_layout_parser_leaves_the_structure_as_well_as_the_text() -> None:
    contract = contract_for(StepKind.document_ai_layout)

    assert contract.produces == (Artifact.text, Artifact.layout)


def test_ocr_before_the_model_is_a_pipeline_that_can_run() -> None:
    assert describe_problems(pipeline(ocr(), extract(), name="ocr first")) == []


def test_a_pipeline_that_reads_text_does_not_need_a_vision_model() -> None:
    assert requires_vision(pipeline(layout(), extract(), name="layout first")) is False


def test_a_pipeline_that_renders_and_ocrs_still_needs_vision() -> None:
    # Both artifacts are there, and the model is handed the images.
    assert requires_vision(pipeline(ocr(), render(), extract(), name="both")) is True


def lookup(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.master_data_lookup, config=config)


def test_a_lookup_reads_entities_and_leaves_entities() -> None:
    contract = contract_for(StepKind.master_data_lookup)

    assert contract.requires_all == (Artifact.entities,)
    assert contract.produces == (Artifact.entities,)


def test_a_lookup_before_the_model_has_nothing_to_look_up() -> None:
    problems = describe_problems(pipeline(render(), lookup(), extract(), name="backwards"))

    assert any("entities" in problem for problem in problems)


ENTITIES_WITH_DERIVED = [
    EntityDefinition(name="supplier_name", format=EntityFormat.text, description="x"),
    EntityDefinition(name="id_subject", format=EntityFormat.text, description="x", source="derived"),
]


def test_a_derived_entity_nobody_fills_is_a_warning_not_a_refusal() -> None:
    """A pipeline that skips a derived field is a choice, not a mistake.

    Refusing to run it would mean a vision pipeline could not be compared with
    an OCR one the moment either produced a field the other does not.
    """
    incomplete = pipeline(render(), extract(), name="no lookup")

    assert describe_problems(incomplete, entities=ENTITIES_WITH_DERIVED) == []
    warnings = describe_warnings(incomplete, entities=ENTITIES_WITH_DERIVED)
    assert any("id_subject" in warning for warning in warnings)


def test_a_pipeline_that_fills_it_has_nothing_to_warn_about() -> None:
    complete = pipeline(render(), extract(), lookup(target_entity="id_subject"), name="with lookup")

    assert describe_warnings(complete, entities=ENTITIES_WITH_DERIVED) == []


def test_a_broken_pipeline_is_still_refused() -> None:
    backwards = pipeline(extract(), render(), name="backwards")

    assert describe_problems(backwards, entities=ENTITIES_WITH_DERIVED) != []
