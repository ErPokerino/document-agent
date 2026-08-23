"""A long operation must not write back the settings it read when it started.

Loading a 20 GB model takes minutes. Anything changed in the meantime — the
pipeline above all, which is chosen with one click in another section — was
silently reverted when the load finished, because the load wrote back the whole
snapshot it had read at the beginning. The window is simulated here by changing
the stored settings from inside the load itself.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
from app.pipeline.store import PipelineStore
from app.services.settings_store import SettingsStore


READY = {
    "model": "second",
    "status": "ready",
    "load_ms": 1,
    "warmup_ms": 1,
    "total_ms": 2,
    "unloaded_models": 0,
    "profile": "default",
    "already_loaded": False,
    "already_ready": False,
    "warmup_mode": "vision_and_schema",
    "preparation_attempts": 1,
}


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="first", pipeline="Vision extraction"))
    pipelines = PipelineStore(tmp_path / "pipelines")
    pipelines.seed_default()
    pipelines.save(
        PipelineDefinition(
            name="OCR then model",
            steps=[
                PipelineStep(kind=StepKind.document_ai_ocr),
                PipelineStep(kind=StepKind.llm_extract),
            ],
        )
    )

    class DuringTheLoad:
        """Someone picks another pipeline while this model is loading."""

        def __init__(self, base_url: str) -> None:
            pass

        async def list_models(self, excluded_model_ids=None):
            return [ModelInfo(id="first", name="First"), ModelInfo(id="second", name="Second")]

        async def list_vision_models(self, excluded_model_ids=None):
            return await self.list_models(excluded_model_ids)

        async def load_and_warm_model(self, model, **kwargs):
            settings.write(settings.read().model_copy(update={"pipeline": "OCR then model"}))
            return READY

    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "pipeline_store", pipelines)
    monkeypatch.setattr(main, "LMStudioClient", DuringTheLoad)
    main.model_runtime_states.clear()
    main.release_model_operation()
    with TestClient(main.app) as client:
        yield client, settings
    main.model_runtime_states.clear()
    main.release_model_operation()


def test_a_pipeline_chosen_during_a_load_survives_the_load(api) -> None:
    client, settings = api

    assert client.post("/api/models/load", json={"model": "second"}).status_code == 200

    after = settings.read()
    assert after.pipeline == "OCR then model", "the load reverted a choice made while it ran"
    assert after.model == "second", "and it still recorded the model it loaded"
