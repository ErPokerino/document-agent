"""Which models may be selected depends on what the pipeline asks of them."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
from app.pipeline.store import PipelineStore
from app.services.settings_store import SettingsStore


VISION = ModelInfo(id="sees", name="Sees", vision=True, loaded=True)
TEXT_ONLY = ModelInfo(id="reads", name="Reads", vision=False, loaded=True)


class FakeLMStudio:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        return [VISION, TEXT_ONLY]

    async def list_vision_models(self, excluded_model_ids=None):
        return [VISION]


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="sees"))
    pipelines = PipelineStore(tmp_path / "pipelines")
    pipelines.seed_default()
    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "pipeline_store", pipelines)
    monkeypatch.setattr(main, "LMStudioClient", FakeLMStudio)
    with TestClient(main.app) as client:
        yield client, pipelines


def save_ocr_pipeline(pipelines: PipelineStore) -> None:
    """A pipeline whose model is handed text, not page images."""
    pipelines.save(
        PipelineDefinition(
            name="text only",
            steps=[
                PipelineStep(kind=StepKind.document_ai_ocr),
                PipelineStep(kind=StepKind.llm_extract),
            ],
        )
    )


def test_a_text_only_model_is_offered_in_the_list(api) -> None:
    client, _ = api

    listed = client.get("/api/models").json()

    assert {model["id"]: model["vision"] for model in listed if model["provider"] == "lm_studio"} == {
        "sees": True,
        "reads": False,
    }


def test_a_pipeline_that_sends_images_refuses_a_model_that_cannot_see(api) -> None:
    client, _ = api
    settings = client.get("/api/settings").json()
    settings["model"] = "reads"

    response = client.put("/api/settings", json=settings)

    assert response.status_code == 400
    assert "vision" in response.json()["detail"].lower()


def test_a_pipeline_that_only_sends_text_accepts_a_model_without_vision(api) -> None:
    client, pipelines = api
    save_ocr_pipeline(pipelines)
    settings = client.get("/api/settings").json()
    settings["model"] = "reads"
    settings["pipeline"] = "text only"

    assert client.put("/api/settings", json=settings).status_code == 200


def test_a_text_only_model_that_is_ready_is_allowed_to_run(api, monkeypatch, tmp_path) -> None:
    """Readiness used to be checked against the vision models only.

    A text-only model was therefore never found, so it was never ready, and an
    OCR pipeline that had every right to run was refused — while the model list
    on screen showed it as ready.
    """
    import pymupdf

    from app.domain.models import FieldExtraction
    from app.pipeline import steps as step_module
    from app.services.run_store import RunStore

    client, pipelines = api
    save_ocr_pipeline(pipelines)
    settings = client.get("/api/settings").json()
    settings["model"] = "reads"
    settings["pipeline"] = "text only"
    settings["gcp"] = {**settings["gcp"], "project_id": "p", "ocr_processor_id": "ocr"}
    assert client.put("/api/settings", json=settings).status_code == 200

    class FakeExtraction:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, *args, **kwargs):
            return {"document_number": FieldExtraction(value="INV-7", confidence="high")}

    class FakeDocumentAi:
        async def process(self, processor_id, content):
            return {"document": {"text": "ACME LTD"}}

    monkeypatch.setattr(step_module, "LMStudioClient", FakeExtraction)
    monkeypatch.setattr(
        step_module.ReadWithDocumentAi, "_client", lambda self, context: FakeDocumentAi()
    )
    monkeypatch.setattr(main, "run_store", RunStore(tmp_path / "docuflow.db"))
    main.model_runtime_states["reads"] = "ready"

    document = pymupdf.open()
    document.new_page()
    content = document.tobytes()
    document.close()

    response = client.post(
        "/api/documents/extract", files={"file": ("a.pdf", content, "application/pdf")}
    )

    assert response.status_code == 200, response.text
