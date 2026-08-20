import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, FieldExtraction, ModelInfo, PromptConfiguration
from app.evaluation.datasets import DatasetStore
from app.evaluation.store import EvaluationStore
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore


READY_MODEL = ModelInfo(id="vision-model", name="Vision Model", loaded=True)


class FakeClient:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_vision_models(self, excluded_model_ids=None):
        return [READY_MODEL]


def pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Invoice")
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "run_store", RunStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(main, "evaluation_store", EvaluationStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(main, "dataset_store", DatasetStore(tmp_path / "datasets"))
    monkeypatch.setattr(main, "LMStudioClient", FakeClient)
    main.model_runtime_states.clear()
    main.release_model_operation()
    with TestClient(main.app) as client:
        yield client
    main.model_runtime_states.clear()
    main.release_model_operation()


def test_datasets_start_empty(api) -> None:
    assert api.get("/api/datasets").json() == []


def test_a_dataset_can_be_created_and_listed(api) -> None:
    assert api.post("/api/datasets", json={"name": "invoices"}).status_code == 201

    assert api.get("/api/datasets").json() == [
        {"name": "invoices", "document_count": 0, "labelled_count": 0}
    ]


def test_creating_a_duplicate_dataset_conflicts(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})

    assert api.post("/api/datasets", json={"name": "invoices"}).status_code == 409


def test_a_dataset_name_that_escapes_the_folder_is_rejected(api) -> None:
    assert api.post("/api/datasets", json={"name": "../escape"}).status_code == 400


def test_a_pdf_can_be_uploaded_and_labelled(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})

    upload = api.post(
        "/api/datasets/invoices/documents",
        files={"file": ("invoice21.pdf", pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 201
    assert upload.json()["labelled"] is False

    labelled = api.put(
        "/api/datasets/invoices/documents/invoice21.pdf/labels",
        json={"labels": {"currency": "EUR", "total_amount": 125.31}},
    )
    assert labelled.status_code == 200
    assert labelled.json()["labels"] == {"currency": "EUR", "total_amount": 125.31}
    assert api.get("/api/datasets").json()[0]["labelled_count"] == 1


def test_labels_naming_an_unconfigured_entity_are_refused(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})
    api.post(
        "/api/datasets/invoices/documents",
        files={"file": ("invoice21.pdf", pdf_bytes(), "application/pdf")},
    )

    response = api.put(
        "/api/datasets/invoices/documents/invoice21.pdf/labels",
        json={"labels": {"not_an_entity": "x"}},
    )

    assert response.status_code == 400
    assert "not_an_entity" in response.json()["detail"]


def test_a_non_pdf_upload_is_refused(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})

    response = api.post(
        "/api/datasets/invoices/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415


def test_documents_of_an_unknown_dataset_are_a_404(api) -> None:
    assert api.get("/api/datasets/nope/documents").status_code == 404


def test_a_reviewed_run_can_be_promoted_to_ground_truth(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})
    run_id = main.run_store.record_run(
        filename="historic.pdf",
        content=pdf_bytes(),
        model="vision-model",
        prompts=PromptConfiguration(),
        extraction={},
        page_count=1,
        processed_pages=1,
        elapsed_ms=100,
    )
    api.post(f"/api/runs/{run_id}/corrections", json={"corrections": {"currency": "EUR"}})

    promoted = api.post("/api/datasets/invoices/documents/from-run", json={"run_ids": [run_id]})

    assert promoted.status_code == 201
    assert promoted.json()[0]["labelled"] is True
    labels = api.get("/api/datasets/invoices/documents/historic.pdf/labels").json()
    assert labels["labels"] == {"currency": "EUR"}
    assert labels["source"] == "promoted_run"


def test_promoting_an_unknown_run_is_a_404(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})

    assert api.post("/api/datasets/invoices/documents/from-run", json={"run_ids": [999]}).status_code == 404


def test_corrections_for_an_unknown_run_are_a_404(api) -> None:
    assert api.post("/api/runs/999/corrections", json={"corrections": {"a": 1}}).status_code == 404


def test_an_evaluation_needs_labelled_documents(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})
    api.post(
        "/api/datasets/invoices/documents",
        files={"file": ("invoice21.pdf", pdf_bytes(), "application/pdf")},
    )
    main.model_runtime_states["vision-model"] = "ready"

    response = api.post("/api/evaluations", json={"dataset": "invoices"})

    assert response.status_code == 400
    assert "ground truth" in response.json()["detail"]


def test_an_evaluation_needs_a_ready_model(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})
    api.post(
        "/api/datasets/invoices/documents",
        files={"file": ("invoice21.pdf", pdf_bytes(), "application/pdf")},
    )
    api.put(
        "/api/datasets/invoices/documents/invoice21.pdf/labels",
        json={"labels": {"currency": "EUR"}},
    )

    response = api.post("/api/evaluations", json={"dataset": "invoices"})

    assert response.status_code == 409
    assert "Load & warm up" in response.json()["detail"]


def test_an_evaluation_blocks_document_processing_while_it_runs(api) -> None:
    main.claim_model_operation("evaluating")

    response = api.post(
        "/api/documents/extract",
        files={"file": ("invoice.pdf", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 409
    assert "Prompt Lab" in response.json()["detail"]


def test_an_unknown_evaluation_is_a_404(api) -> None:
    assert api.get("/api/evaluations/999").status_code == 404


def test_cancelling_a_finished_evaluation_conflicts(api) -> None:
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="vision-model", prompts=PromptConfiguration(), total_documents=1
    )
    main.evaluation_store.finish(evaluation_id, "completed")

    assert api.post(f"/api/evaluations/{evaluation_id}/cancel").status_code == 409


def seed_document(api, dataset="invoices", name="invoice21.pdf"):
    api.post("/api/datasets", json={"name": dataset})
    api.post(
        f"/api/datasets/{dataset}/documents",
        files={"file": (name, pdf_bytes(), "application/pdf")},
    )


def record_reviewed_run(filename: str, corrections: dict) -> int:
    run_id = main.run_store.record_run(
        filename=filename,
        content=pdf_bytes() + filename.encode(),
        model="vision-model",
        prompts=PromptConfiguration(),
        extraction={},
        page_count=1,
        processed_pages=1,
        elapsed_ms=100,
    )
    main.run_store.record_corrections(run_id, corrections)
    return run_id


def test_an_evaluation_can_be_deleted(api) -> None:
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="vision-model", prompts=PromptConfiguration(), total_documents=1
    )
    main.evaluation_store.finish(evaluation_id, "completed")

    assert api.delete(f"/api/evaluations/{evaluation_id}").status_code == 204
    assert api.get(f"/api/evaluations/{evaluation_id}").status_code == 404


def test_deleting_an_unknown_evaluation_is_a_404(api) -> None:
    assert api.delete("/api/evaluations/999").status_code == 404


def test_a_running_evaluation_cannot_be_deleted(api) -> None:
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="vision-model", prompts=PromptConfiguration(), total_documents=1
    )

    assert api.delete(f"/api/evaluations/{evaluation_id}").status_code == 409


def test_several_reviewed_runs_are_promoted_in_one_call(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})
    first = record_reviewed_run("one.pdf", {"currency": "EUR"})
    second = record_reviewed_run("two.pdf", {"currency": "USD"})

    response = api.post(
        "/api/datasets/invoices/documents/from-run", json={"run_ids": [first, second]}
    )

    assert response.status_code == 201
    assert {document["name"] for document in response.json()} == {"one.pdf", "two.pdf"}
    assert api.get("/api/datasets").json()[0]["labelled_count"] == 2


def test_promoting_a_batch_with_an_unknown_run_is_a_404(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})
    known = record_reviewed_run("one.pdf", {"currency": "EUR"})

    assert api.post(
        "/api/datasets/invoices/documents/from-run", json={"run_ids": [known, 999]}
    ).status_code == 404


def test_draft_labels_need_a_ready_model(api) -> None:
    seed_document(api)

    response = api.post("/api/datasets/invoices/documents/invoice21.pdf/draft-labels")

    assert response.status_code == 409
    assert "Load & warm up" in response.json()["detail"]


def test_draft_labels_are_proposed_by_the_model_and_not_saved(api, monkeypatch) -> None:
    seed_document(api)
    main.model_runtime_states["vision-model"] = "ready"

    class FakeExtractor:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages):
            return {
                "currency": FieldExtraction(value="EUR", confidence="high"),
                "total_amount": FieldExtraction(value=125.31, confidence="low"),
            }

    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", FakeExtractor)

    response = api.post("/api/datasets/invoices/documents/invoice21.pdf/draft-labels")

    assert response.status_code == 200
    body = response.json()
    assert body["labels"] == {"currency": "EUR", "total_amount": 125.31}
    assert body["confidence"] == {"currency": "high", "total_amount": "low"}
    # A draft is a proposal: nothing is ground truth until a person saves it.
    assert api.get("/api/datasets/invoices/documents").json()[0]["labelled"] is False


def test_a_draft_is_refused_while_the_model_is_busy(api) -> None:
    seed_document(api)
    main.model_runtime_states["vision-model"] = "ready"
    main.claim_model_operation("evaluating")

    assert api.post("/api/datasets/invoices/documents/invoice21.pdf/draft-labels").status_code == 409


def test_the_page_limit_is_recorded_on_the_evaluation(api, monkeypatch) -> None:
    seed_document(api)
    api.put(
        "/api/datasets/invoices/documents/invoice21.pdf/labels",
        json={"labels": {"currency": "EUR"}},
    )
    main.model_runtime_states["vision-model"] = "ready"
    settings = main.settings_store.read()
    main.settings_store.write(settings.model_copy(update={"max_pages_to_analyze": 7}))

    class Idle:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, *args, **kwargs):
            return {"currency": FieldExtraction(value="EUR", confidence="high")}

    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", Idle)
    response = api.post("/api/evaluations", json={"dataset": "invoices"})

    assert response.status_code == 202
    assert response.json()["max_pages"] == 7
