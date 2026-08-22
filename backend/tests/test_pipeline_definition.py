import pytest

from app.pipeline.definition import (
    Artifact,
    PipelineDefinition,
    PipelineStep,
    StepKind,
    contract_for,
    describe_problems,
)


def render(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.render_pages, config={"max_pages": 1, "scale": 1.35, **config})


def extract(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.llm_extract, config={"provider": "gemini", "model": "gemini-3.7-flash", **config})


def regex(**config) -> PipelineStep:
    return PipelineStep(kind=StepKind.regex_refine, config={"rules": [], **config})


def pipeline(*steps: PipelineStep, name: str = "test") -> PipelineDefinition:
    return PipelineDefinition(name=name, steps=list(steps))


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
