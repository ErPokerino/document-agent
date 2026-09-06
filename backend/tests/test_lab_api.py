import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, FieldExtraction, ModelInfo, PromptConfiguration
from app.evaluation.datasets import DatasetStore
from app.evaluation.store import EvaluationStore
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore


def test_lab_pins_the_invoked_extractor_and_its_retry_definition(api, monkeypatch):
    """Changing the remote default after start must not change executable steps."""
    from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
    from app.services.document_ai import DocumentAiClient
    from unittest.mock import AsyncMock
    from threading import Event

    seed_document(api)
    api.put("/api/datasets/invoices/documents/invoice21.pdf/labels", json={"labels": {"currency": "EUR"}})
    definition = PipelineDefinition(name="Pinned extractor", steps=[PipelineStep(kind=StepKind.document_ai_extract, config={"processor_id": "p"})])
    main.pipeline_store.save(definition)
    settings = main.settings_store.read()
    settings.pipeline = definition.name
    settings.gcp.project_id = "project"
    main.settings_store.write(settings)
    resource = "projects/project/locations/eu/processors/p"
    monkeypatch.setattr(DocumentAiClient, "metadata", AsyncMock(side_effect=[{"name": resource, "displayName": "Invoices", "defaultProcessorVersion": resource + "/processorVersions/v3"}, {}]))
    seen = []
    executed = Event()

    async def run(**kwargs):
        seen.extend(step.processor_id for step in kwargs["steps"] if type(step).__name__ == "ExtractWithCustomExtractor")
        main.evaluation_store.finish(kwargs["evaluation_id"], "completed")
        executed.set()

    monkeypatch.setattr(main, "run_evaluation", run)
    response = api.post("/api/evaluations", json={"dataset": "invoices"})
    assert response.status_code == 202
    assert response.json()["extraction_engine"]["version"] == "v3"
    detail = main.evaluation_store.get_evaluation(response.json()["id"])
    assert detail.pipeline_definition.steps[0].config["processor_id"] == "p/processorVersions/v3"
    assert executed.wait(2), "The evaluation worker did not start"
    assert seen == ["p/processorVersions/v3"]


READY_MODEL = ModelInfo(id="vision-model", name="Vision Model", loaded=True)


class FakeClient:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        return [READY_MODEL]

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
    main.model_runtime_profiles.clear()
    main.release_model_operation()
    with TestClient(main.app) as client:
        yield client
    main.model_runtime_states.clear()
    main.model_runtime_profiles.clear()
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
    assert "Lab" in response.json()["detail"]


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

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
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
    definition = main.pipeline_store.read(main.settings_store.read().pipeline)
    definition.page_limit = 7
    main.pipeline_store.save(definition)

    class Idle:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, *args, **kwargs):
            return {"currency": FieldExtraction(value="EUR", confidence="high")}

    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", Idle)
    response = api.post("/api/evaluations", json={"dataset": "invoices"})

    assert response.status_code == 202
    assert response.json()["max_pages"] == 7


def test_a_dataset_can_be_renamed(api) -> None:
    seed_document(api)

    response = api.patch("/api/datasets/invoices", json={"name": "invoices-2026"})

    assert response.status_code == 200
    assert response.json()["name"] == "invoices-2026"
    assert [dataset["name"] for dataset in api.get("/api/datasets").json()] == ["invoices-2026"]
    assert api.get("/api/datasets/invoices-2026/documents").json()[0]["name"] == "invoice21.pdf"


def test_renaming_onto_an_existing_dataset_conflicts(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})
    api.post("/api/datasets", json={"name": "receipts"})

    assert api.patch("/api/datasets/invoices", json={"name": "receipts"}).status_code == 409


def test_renaming_an_unknown_dataset_is_a_404(api) -> None:
    assert api.patch("/api/datasets/nope", json={"name": "other"}).status_code == 404


def test_renaming_to_an_unsafe_name_is_rejected(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})

    assert api.patch("/api/datasets/invoices", json={"name": "../escape"}).status_code == 400


def labelled_dataset(api, names=("a.pdf", "b.pdf")):
    api.post("/api/datasets", json={"name": "invoices"})
    for name in names:
        api.post(
            "/api/datasets/invoices/documents",
            files={"file": (name, pdf_bytes(), "application/pdf")},
        )
        api.put(
            f"/api/datasets/invoices/documents/{name}/labels",
            json={"labels": {"currency": "EUR"}},
        )


def wait_for_run(api, evaluation_id: int, attempts: int = 100) -> dict:
    """Poll the way the UI does: the retry runs as a background task."""
    for _ in range(attempts):
        body = api.get(f"/api/evaluations/{evaluation_id}").json()
        if body["status"] != "running":
            return body
    raise AssertionError(f"evaluation {evaluation_id} never left the running state")


def snapshot_dataset() -> dict:
    return {
        doc.name: {
            "sha256": main.evaluation_store.snapshot_document(main.dataset_store.read_document("invoices", doc.name)),
            "labels": main.dataset_store.read_labels("invoices", doc.name).labels,
        }
        for doc in main.dataset_store.list_documents("invoices")
    }


def partial_run(api) -> int:
    """One document scored, one failed: the case the UI was calling "completed"."""
    evaluation_id = main.evaluation_store.start(
        dataset="invoices",
        model="vision-model",
        prompts=PromptConfiguration(),
        total_documents=2,
        max_pages=1,
        dataset_snapshot=snapshot_dataset(),
    )
    main.evaluation_store.record_document(evaluation_id, "b.pdf", [], elapsed_ms=1000)
    main.evaluation_store.record_document_failure(evaluation_id, "a.pdf", "Model is unloaded")
    main.evaluation_store.complete(evaluation_id)
    return evaluation_id


def test_a_run_with_failures_is_reported_as_partial(api) -> None:
    labelled_dataset(api)
    evaluation_id = partial_run(api)

    body = api.get(f"/api/evaluations/{evaluation_id}").json()

    assert body["status"] == "partial"
    assert body["succeeded_documents"] == 1
    assert body["failed_documents"] == 1


def test_documents_a_run_never_reached_are_counted_as_pending(api) -> None:
    labelled_dataset(api)
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="vision-model", prompts=PromptConfiguration(), total_documents=3
    )
    main.evaluation_store.record_document(evaluation_id, "b.pdf", [], elapsed_ms=1)
    main.evaluation_store.complete(evaluation_id)

    body = api.get(f"/api/evaluations/{evaluation_id}").json()

    assert body["status"] == "partial"
    assert body["pending_documents"] == 2


@pytest.mark.parametrize("mutation", ["none", "add", "labels", "replace", "rename", "delete"])
def test_retrying_uses_only_the_original_unfinished_inputs(api, monkeypatch, mutation) -> None:
    """Dataset edits must not change the inputs, labels or size of a retry."""
    labelled_dataset(api)
    evaluation_id = partial_run(api)
    main.model_runtime_states["vision-model"] = "ready"
    seen: list[str] = []

    class Recovered:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
            return {"currency": FieldExtraction(value="EUR", confidence="high")}

    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", Recovered)
    original_read = main.evaluation_store.read_snapshot_document
    original_digest = main.evaluation_store.get_evaluation(evaluation_id).dataset_snapshot["a.pdf"]["sha256"]

    def spy(digest):
        seen.append(digest)
        return original_read(digest)

    monkeypatch.setattr(main.evaluation_store, "read_snapshot_document", spy)
    if mutation == "add":
        main.dataset_store.add_document("invoices", "new.pdf", pdf_bytes(), labels={"currency": "USD"})
    elif mutation == "labels":
        main.dataset_store.set_labels("invoices", "a.pdf", {"currency": "USD"})
    elif mutation == "replace":
        main.dataset_store.remove_document("invoices", "a.pdf")
        main.dataset_store.add_document("invoices", "a.pdf", b"not even a PDF", labels={"currency": "USD"})
    elif mutation == "rename":
        main.dataset_store.rename("invoices", "renamed")
    elif mutation == "delete":
        main.dataset_store.delete("invoices")

    response = api.post(f"/api/evaluations/{evaluation_id}/retry")

    assert response.status_code == 202
    detail = wait_for_run(api, evaluation_id)
    # b.pdf already succeeded, so the model is not asked about it again.
    assert seen == [original_digest]
    assert detail["status"] == "completed"
    assert detail["failed_documents"] == 0
    assert detail["succeeded_documents"] == 2
    assert detail["total_documents"] == 2
    assert detail["metrics"]["accuracy"] == 1


def test_retrying_requires_the_model_the_run_used(api) -> None:
    labelled_dataset(api)
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="another-model", prompts=PromptConfiguration(), total_documents=2,
        dataset_snapshot=snapshot_dataset(),
    )
    main.evaluation_store.record_document_failure(evaluation_id, "a.pdf", "boom")
    main.evaluation_store.complete(evaluation_id)
    main.model_runtime_states["vision-model"] = "ready"

    response = api.post(f"/api/evaluations/{evaluation_id}/retry")

    assert response.status_code == 409
    assert "another-model" in response.json()["detail"]


def test_retrying_refuses_a_different_model_execution_profile(api) -> None:
    """A retry must not merge results produced under different runtime controls."""
    from app.domain.models import ModelExecutionProfile

    labelled_dataset(api)
    evaluation_id = main.evaluation_store.start(
        dataset="invoices",
        model="vision-model",
        prompts=PromptConfiguration(),
        total_documents=2,
        dataset_snapshot=snapshot_dataset(),
        execution_profile=ModelExecutionProfile(
            provider="lm_studio",
            profile="standard",
            context_length=4096,
            parallel=1,
            temperature=0,
            seed=0,
        ),
    )
    main.evaluation_store.record_document_failure(evaluation_id, "a.pdf", "boom")
    main.evaluation_store.complete(evaluation_id)
    main.model_runtime_states["vision-model"] = "ready"
    main.model_runtime_profiles["vision-model"] = "standard"

    response = api.post(f"/api/evaluations/{evaluation_id}/retry")

    assert response.status_code == 409
    assert "execution profile differs" in response.json()["detail"]


def test_retrying_a_run_with_nothing_left_to_do_is_refused(api) -> None:
    labelled_dataset(api, names=("a.pdf",))
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="vision-model", prompts=PromptConfiguration(), total_documents=1,
        dataset_snapshot=snapshot_dataset(),
    )
    main.evaluation_store.record_document(
        evaluation_id, "a.pdf", [], elapsed_ms=1
    )
    main.evaluation_store.complete(evaluation_id)
    main.model_runtime_states["vision-model"] = "ready"

    response = api.post(f"/api/evaluations/{evaluation_id}/retry")

    assert response.status_code == 400
    assert "nothing left" in response.json()["detail"].lower()


def test_retrying_a_legacy_run_without_input_snapshots_is_refused(api) -> None:
    labelled_dataset(api)
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="vision-model", prompts=PromptConfiguration(), total_documents=2,
    )
    main.evaluation_store.finish(evaluation_id, "failed")
    main.model_runtime_states["vision-model"] = "ready"
    api.delete("/api/datasets/invoices")

    response = api.post(f"/api/evaluations/{evaluation_id}/retry")
    assert response.status_code == 409
    assert "no snapshot" in response.json()["detail"]


def test_retrying_a_running_evaluation_conflicts(api) -> None:
    labelled_dataset(api)
    evaluation_id = main.evaluation_store.start(
        dataset="invoices", model="vision-model", prompts=PromptConfiguration(), total_documents=2
    )
    main.model_runtime_states["vision-model"] = "ready"

    assert api.post(f"/api/evaluations/{evaluation_id}/retry").status_code == 409


def test_a_dataset_document_can_be_fetched_for_preview(api) -> None:
    seed_document(api)

    response = api.get("/api/datasets/invoices/documents/invoice21.pdf/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert "inline" in response.headers.get("content-disposition", "")


def test_fetching_an_unknown_document_is_a_404(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})

    assert api.get("/api/datasets/invoices/documents/nope.pdf/file").status_code == 404


def test_a_document_path_that_escapes_the_dataset_is_rejected(api) -> None:
    api.post("/api/datasets", json={"name": "invoices"})

    assert api.get("/api/datasets/invoices/documents/..%2F..%2Fsecret.pdf/file").status_code in (400, 404)


def test_a_run_can_be_exported_as_csv(api) -> None:
    labelled_dataset(api)
    evaluation_id = partial_run(api)

    response = api.get(f"/api/evaluations/{evaluation_id}/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f"run-{evaluation_id}" in response.headers.get("content-disposition", "")
    assert response.text.splitlines()[0].startswith("run_id,")
    assert "a.pdf" in response.text


def test_exporting_an_unknown_run_is_a_404(api) -> None:
    assert api.get("/api/evaluations/999/export.csv").status_code == 404


def test_the_prompt_preview_shows_what_the_local_model_will_receive(api) -> None:
    prompts = PromptConfiguration()

    body = api.post(
        "/api/prompts/preview",
        json={"prompts": prompts.model_dump(mode="json"), "provider": "lm_studio"},
    ).json()

    # The assembled prompt carries the entity list the user never typed.
    assert "supplier_name" in body["system_prompt"]
    assert prompts.system_prompt.strip() in body["system_prompt"]
    assert '"c"' in body["generation_schema"]
    assert body["output_token_budget"] > 0


def test_the_preview_reflects_the_provider(api) -> None:
    prompts = PromptConfiguration()

    body = api.post(
        "/api/prompts/preview",
        json={"prompts": prompts.model_dump(mode="json"), "provider": "gemini"},
    ).json()

    # Gemini gets a different schema, and the preview must say so rather than
    # showing the local one.
    assert "pattern" not in body["generation_schema"]
    assert "confidence" in body["generation_schema"]
    assert body["output_token_budget"] is None


def test_a_preview_of_an_edited_prompt_uses_the_edit(api) -> None:
    prompts = PromptConfiguration()
    prompts.system_prompt = "A completely different instruction"

    body = api.post(
        "/api/prompts/preview",
        json={"prompts": prompts.model_dump(mode="json"), "provider": "lm_studio"},
    ).json()

    assert "A completely different instruction" in body["system_prompt"]


def test_a_duplicate_upload_returns_a_conflict_and_preserves_ground_truth(api) -> None:
    """A duplicate filename is not an instruction to replace a labelled PDF."""
    labelled_dataset(api, names=("a.pdf",))
    original = main.dataset_store.read_document("invoices", "a.pdf")
    response = api.post("/api/datasets/invoices/documents", files={"file": ("a.pdf", pdf_bytes(), "application/pdf")})
    assert response.status_code == 409
    assert main.dataset_store.read_document("invoices", "a.pdf") == original
    assert main.dataset_store.read_labels("invoices", "a.pdf").labels == {"currency": "EUR"}


def test_a_promotion_batch_with_duplicate_names_writes_nothing(api) -> None:
    """Two reviewed runs may share a filename without being the same document."""
    api.post("/api/datasets", json={"name": "invoices"})
    ids = [main.run_store.record_run(filename="same.pdf", content=pdf_bytes(), model="m", prompts=PromptConfiguration(), extraction={}, page_count=1, processed_pages=1, elapsed_ms=1) for _ in range(2)]
    response = api.post("/api/datasets/invoices/documents/from-run", json={"run_ids": ids})
    assert response.status_code == 409
    assert main.dataset_store.list_documents("invoices") == []


def test_history_cursors_reach_every_evaluation_without_duplicates(api) -> None:
    """Lab filters and exports must also reach runs older than the first page."""
    for _ in range(53):
        main.evaluation_store.start(dataset="invoices", model="m", prompts=PromptConfiguration(), total_documents=1)
    first = api.get("/api/evaluations?limit=50").json()
    second = api.get(f"/api/evaluations?limit=50&before_id={first[-1]['id']}").json()
    assert [row["id"] for row in first + second] == list(range(53, 0, -1))
    assert api.get("/api/evaluations?limit=0").status_code == 422
    assert api.get("/api/runs?limit=-1").status_code == 422


def test_an_evaluation_started_over_the_api_captures_its_inputs(api, monkeypatch) -> None:
    """Snapshotting in the store alone would not protect the actual start route."""
    from app.pipeline import steps
    labelled_dataset(api, names=("a.pdf",))
    original = main.dataset_store.read_document("invoices", "a.pdf")
    class Reader:
        async def extract_entities(self, *args, **kwargs):
            return {"currency": FieldExtraction(value="EUR", confidence="high")}
    monkeypatch.setattr(steps, "build_extraction_client", lambda context: Reader())
    main.model_runtime_states["vision-model"] = "ready"
    response = api.post("/api/evaluations", json={"dataset": "invoices"})
    assert response.status_code == 202, response.text
    eid = response.json()["id"]
    wait_for_run(api, eid)
    snapshot = main.evaluation_store.get_evaluation(eid).dataset_snapshot
    assert snapshot["a.pdf"]["labels"] == {"currency": "EUR"}
    assert main.evaluation_store.read_snapshot_document(snapshot["a.pdf"]["sha256"]) == original


def test_evaluation_preview_uses_the_snapshot_after_dataset_removal(api) -> None:
    """Reading a historical result must show the PDF that was actually scored."""
    labelled_dataset(api)
    original = main.dataset_store.read_document("invoices", "a.pdf")
    eid = partial_run(api)
    main.dataset_store.delete("invoices")
    response = api.get(f"/api/evaluations/{eid}/documents/a.pdf/file")
    assert response.status_code == 200
    assert response.content == original
    assert api.get(f"/api/evaluations/{eid}/documents/unknown.pdf/file").status_code == 404
