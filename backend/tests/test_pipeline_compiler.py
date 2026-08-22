import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction, PromptConfiguration
from app.pipeline.compiler import PipelineError, build_steps
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.steps import ExtractEntities, InspectPdf, RefineWithRegex, RenderPages


ENTITIES = [EntityDefinition(name="document_number", format=EntityFormat.text, description="x")]
PROMPTS = PromptConfiguration(entities=ENTITIES)


def compile_it(definition: PipelineDefinition, **kwargs):
    return build_steps(definition, prompts=PROMPTS, entities=ENTITIES, **kwargs)


def test_the_default_pipeline_compiles_to_inspect_render_extract() -> None:
    steps = compile_it(PipelineDefinition.default())

    assert [type(step) for step in steps] == [InspectPdf, RenderPages, ExtractEntities]


def test_the_page_limit_comes_from_the_pipeline() -> None:
    default = PipelineDefinition.default()
    default.page_limit = 7

    assert compile_it(default)[0].max_pages_to_analyze == 7


def test_the_render_scale_is_taken_from_the_step_configuration() -> None:
    definition = PipelineDefinition(
        name="sharp",
        steps=[
            PipelineStep(kind=StepKind.render_pages, config={"scale": 2.0}),
            PipelineStep(kind=StepKind.llm_extract),
        ],
    )

    assert compile_it(definition)[1].scale == 2.0


def test_regex_rules_are_turned_into_a_refinement_step() -> None:
    definition = PipelineDefinition(
        name="cleanup",
        steps=[
            PipelineStep(kind=StepKind.render_pages),
            PipelineStep(kind=StepKind.llm_extract),
            PipelineStep(
                kind=StepKind.regex_refine,
                config={"rules": [{"entity": "document_number", "pattern": r"\s+", "replacement": ""}]},
            ),
        ],
    )

    steps = compile_it(definition)

    assert isinstance(steps[-1], RefineWithRegex)
    assert steps[-1].rules[0].entity == "document_number"


def test_a_pipeline_that_could_not_run_is_refused_before_a_document_is_touched() -> None:
    definition = PipelineDefinition(
        name="backwards",
        steps=[
            PipelineStep(kind=StepKind.llm_extract),
            PipelineStep(kind=StepKind.render_pages),
        ],
    )

    with pytest.raises(PipelineError) as error:
        compile_it(definition)

    assert "images or text" in str(error.value)


def test_an_unusable_rule_is_refused_with_the_step_that_carries_it() -> None:
    definition = PipelineDefinition(
        name="bad-rule",
        steps=[
            PipelineStep(kind=StepKind.render_pages),
            PipelineStep(kind=StepKind.llm_extract),
            PipelineStep(
                kind=StepKind.regex_refine,
                config={"rules": [{"entity": "document_number", "pattern": "([unclosed"}]},
            ),
        ],
    )

    with pytest.raises(PipelineError, match="Step 3"):
        compile_it(definition)


@pytest.mark.asyncio
async def test_the_compiled_default_pipeline_extracts_a_document(monkeypatch, tmp_path) -> None:
    import pymupdf

    from app.pipeline import steps as step_module

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages):
            assert images, "the render step must have produced page images"
            return {"document_number": FieldExtraction(value="INV 7", confidence="high")}

    monkeypatch.setattr(step_module, "LMStudioClient", FakeClient)

    document = pymupdf.open()
    document.new_page()
    content = document.tobytes()
    document.close()

    definition = PipelineDefinition(
        name="clean",
        steps=[
            PipelineStep(kind=StepKind.render_pages),
            PipelineStep(kind=StepKind.llm_extract),
            PipelineStep(
                kind=StepKind.regex_refine,
                config={"rules": [{"entity": "document_number", "pattern": r"\s+", "replacement": "-"}]},
            ),
        ],
    )
    context = PipelineContext(
        filename="a.pdf", content=content, model="m", lm_studio_url="http://localhost:1234"
    )

    result = await DocumentPipeline(compile_it(definition)).run(context)

    # The rule ran after the model, on what the model returned.
    assert result.artifacts["extraction"]["document_number"].value == "INV-7"
