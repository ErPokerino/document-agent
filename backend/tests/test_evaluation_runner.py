import asyncio

import pymupdf
import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction, PromptConfiguration
from app.evaluation.datasets import DatasetStore
from app.evaluation.runner import run_evaluation
from app.pipeline.compiler import build_steps
from app.pipeline.engine import PipelineContext
from app.services.document_ai import DocumentAiError
from app.pipeline.definition import PipelineDefinition
from app.evaluation.store import EvaluationStore
from app.services.lm_studio import LMStudioError


ENTITIES = [EntityDefinition(name="currency", format=EntityFormat.currency, description="x")]


def pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Invoice")
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def workspace(tmp_path):
    datasets = DatasetStore(tmp_path / "datasets")
    datasets.create("invoices")
    for name in ("a.pdf", "b.pdf"):
        datasets.add_document("invoices", name, pdf_bytes(), labels={"currency": "EUR"})
    return datasets, EvaluationStore(tmp_path / "docuflow.db")


def fake_client(returns):
    class FakeClient:
        calls = 0

        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
            FakeClient.calls += 1
            value = returns(FakeClient.calls)
            if isinstance(value, Exception):
                raise value
            return {"currency": FieldExtraction(value=value, confidence="high")}

    FakeClient.calls = 0
    return FakeClient



def default_steps(max_pages: int = 1):
    definition = PipelineDefinition.default()
    definition.page_limit = max_pages
    return build_steps(definition, prompts=PromptConfiguration(entities=ENTITIES), entities=ENTITIES)


async def execute(datasets, evaluations, evaluation_id, cancelled=None):
    documents = [(document.name, {"currency": "EUR"}) for document in datasets.list_documents("invoices")]
    await run_evaluation(
        evaluation_id=evaluation_id,
        evaluations=evaluations,
        datasets=datasets,
        run_store=None,
        dataset="invoices",
        documents=documents,
        entities=ENTITIES,
        prompts=PromptConfiguration(entities=ENTITIES),
        model="vision-model",
        max_pages=1,
        steps=default_steps(),
        make_context=lambda name, content: PipelineContext(
            filename=name, content=content, model="vision-model", lm_studio_url="http://localhost:1234"
        ),
        cancelled=cancelled,
    )


async def test_every_document_is_scored_and_the_run_completes(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace
    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", fake_client(lambda n: "EUR"))
    evaluation_id = evaluations.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2)

    await execute(datasets, evaluations, evaluation_id)

    detail = evaluations.get_evaluation(evaluation_id)
    assert detail.status == "completed"
    assert detail.completed_documents == 2
    assert detail.metrics.accuracy == 1.0


async def test_a_wrong_answer_lowers_accuracy_without_failing_the_run(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace
    monkeypatch.setattr(
        "app.pipeline.steps.LMStudioClient", fake_client(lambda n: "EUR" if n == 1 else "USD")
    )
    evaluation_id = evaluations.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2)

    await execute(datasets, evaluations, evaluation_id)

    detail = evaluations.get_evaluation(evaluation_id)
    assert detail.status == "completed"
    assert detail.metrics.accuracy == 0.5


async def test_one_failing_document_does_not_abort_the_others(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace
    monkeypatch.setattr(
        "app.pipeline.steps.LMStudioClient",
        fake_client(lambda n: LMStudioError("the model died") if n == 1 else "EUR"),
    )
    evaluation_id = evaluations.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2)

    await execute(datasets, evaluations, evaluation_id)

    detail = evaluations.get_evaluation(evaluation_id)
    # Not "completed": half the dataset never reached the model.
    assert detail.status == "partial"
    assert detail.succeeded_documents == 1
    assert len(detail.failures) == 1
    assert "the model died" in detail.failures[0][1]
    assert detail.metrics.total == 1


async def test_a_cancelled_run_stops_and_is_marked_cancelled(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace
    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", fake_client(lambda n: "EUR"))
    evaluation_id = evaluations.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2)
    cancelled = asyncio.Event()
    cancelled.set()

    await execute(datasets, evaluations, evaluation_id, cancelled=cancelled)

    detail = evaluations.get_evaluation(evaluation_id)
    assert detail.status == "cancelled"
    assert detail.completed_documents == 0


async def test_labels_naming_an_unconfigured_entity_fail_only_that_document(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace
    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", fake_client(lambda n: "EUR"))
    evaluation_id = evaluations.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2)

    await run_evaluation(
        evaluation_id=evaluation_id,
        evaluations=evaluations,
        datasets=datasets,
        run_store=None,
        dataset="invoices",
        documents=[("a.pdf", {"nonexistent": "x"}), ("b.pdf", {"currency": "EUR"})],
        entities=ENTITIES,
        prompts=PromptConfiguration(entities=ENTITIES),
        model="vision-model",
        max_pages=1,
        steps=default_steps(),
        make_context=lambda name, content: PipelineContext(
            filename=name, content=content, model="vision-model", lm_studio_url="http://localhost:1234"
        ),
    )

    detail = evaluations.get_evaluation(evaluation_id)
    assert len(detail.failures) == 1
    assert detail.metrics.total == 1


async def test_the_token_usage_of_each_document_reaches_the_store(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace

    class CountingClient:
        def __init__(self, base_url: str) -> None:
            self.last_prediction_stats = {"prompt_tokens": 1500, "completion_tokens": 90}

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
            return {"currency": FieldExtraction(value="EUR", confidence="high")}

    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", CountingClient)
    evaluation_id = evaluations.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2)

    await execute(datasets, evaluations, evaluation_id)

    detail = evaluations.get_evaluation(evaluation_id)
    assert detail.prompt_tokens == 3000
    assert detail.completion_tokens == 180


async def test_a_provider_that_reports_nothing_leaves_the_counts_empty(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace
    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", fake_client(lambda n: "EUR"))
    evaluation_id = evaluations.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2)

    await execute(datasets, evaluations, evaluation_id)

    assert evaluations.get_evaluation(evaluation_id).prompt_tokens == 0


async def test_the_run_uses_the_same_context_the_app_builds(workspace, monkeypatch) -> None:
    """A run reads the pipeline's settings from one place, or it reads them wrong.

    The Lab used to assemble its own context and knew nothing about Google
    Cloud, so an OCR pipeline that worked in Workspace failed on every
    document here.
    """
    datasets, evaluations = workspace
    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", fake_client(lambda n: "EUR"))
    evaluation_id = evaluations.start(
        dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=1
    )
    seen: list[PipelineContext] = []

    def make_context(filename: str, content: bytes) -> PipelineContext:
        context = PipelineContext(
            filename=filename,
            content=content,
            model="vision-model",
            lm_studio_url="http://localhost:1234",
            gcp_project_id="a-project",
            gcp_credentials_path="key.json",
        )
        seen.append(context)
        return context

    await run_evaluation(
        evaluation_id=evaluation_id,
        evaluations=evaluations,
        datasets=datasets,
        run_store=None,
        dataset="invoices",
        documents=[("a.pdf", {"currency": "EUR"})],
        entities=ENTITIES,
        prompts=PromptConfiguration(entities=ENTITIES),
        model="vision-model",
        max_pages=1,
        steps=default_steps(),
        make_context=make_context,
    )

    assert [context.gcp_project_id for context in seen] == ["a-project"]


async def test_a_document_ai_failure_costs_one_document_not_the_whole_run(workspace, monkeypatch) -> None:
    datasets, evaluations = workspace
    evaluation_id = evaluations.start(
        dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=2
    )

    class Refuses:
        async def run(self, context) -> None:
            raise DocumentAiError("Document AI refused processor x (403). Permission denied")

    await run_evaluation(
        evaluation_id=evaluation_id,
        evaluations=evaluations,
        datasets=datasets,
        run_store=None,
        dataset="invoices",
        documents=[("a.pdf", {"currency": "EUR"}), ("b.pdf", {"currency": "EUR"})],
        entities=ENTITIES,
        prompts=PromptConfiguration(entities=ENTITIES),
        model="vision-model",
        max_pages=1,
        steps=[Refuses()],
        make_context=lambda name, content: PipelineContext(
            filename=name, content=content, model="m", lm_studio_url="http://x"
        ),
    )

    detail = evaluations.get_evaluation(evaluation_id)
    assert detail.status == "failed"
    assert len(detail.failures) == 2
    assert "Permission denied" in detail.failures[0][1]


async def test_a_run_stops_when_the_runtime_dies_instead_of_hammering_it(workspace, monkeypatch) -> None:
    """qwen3.6-35b-a3b crashed LM Studio on the second page image.

    The eight documents after it each failed in milliseconds against a runtime
    that was no longer there, filling the run with identical errors and hiding
    what had actually happened.
    """
    datasets, evaluations = workspace
    asked: list[str] = []

    class DiesOnTheSecond:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
            asked.append("call")
            if len(asked) == 1:
                return {entity.name: FieldExtraction(value="EUR", confidence="high") for entity in ENTITIES}
            raise LMStudioError('LM Studio rejected the request: {"error":"Model is unloaded."}')

    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", DiesOnTheSecond)
    evaluation_id = evaluations.start(
        dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=5
    )

    await run_evaluation(
        evaluation_id=evaluation_id,
        evaluations=evaluations,
        datasets=datasets,
        run_store=None,
        dataset="invoices",
        documents=[(f"{n}.pdf", {"currency": "EUR"}) for n in "abcde"],
        entities=ENTITIES,
        prompts=PromptConfiguration(entities=ENTITIES),
        model="vision-model",
        max_pages=1,
        steps=default_steps(),
        make_context=lambda name, content: PipelineContext(
            filename=name, content=content, model="m", lm_studio_url="http://x"
        ),
    )

    detail = evaluations.get_evaluation(evaluation_id)
    # One success, one failure that killed it, and nothing attempted after.
    assert len(asked) == 2
    assert detail.succeeded_documents == 1
    assert detail.failed_documents == 1
    assert detail.pending_documents == 3
    assert detail.status == "partial"
    assert "no longer serving" in (detail.error or "")
