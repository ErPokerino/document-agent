import asyncio

import pymupdf
import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction, PromptConfiguration
from app.evaluation.datasets import DatasetStore
from app.evaluation.runner import run_evaluation
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

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages):
            FakeClient.calls += 1
            value = returns(FakeClient.calls)
            if isinstance(value, Exception):
                raise value
            return {"currency": FieldExtraction(value=value, confidence="high")}

    FakeClient.calls = 0
    return FakeClient


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
        lm_studio_url="http://localhost:1234",
        max_pages=1,
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
    assert detail.status == "completed"
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
        lm_studio_url="http://localhost:1234",
        max_pages=1,
    )

    detail = evaluations.get_evaluation(evaluation_id)
    assert len(detail.failures) == 1
    assert detail.metrics.total == 1
