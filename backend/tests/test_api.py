import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.services.lm_studio import LMStudioError
from app.services.settings_store import SettingsStore


READY_MODEL = ModelInfo(id="vision-model", name="Vision Model", loaded=True)


class FakeClient:
    """Configurable stand-in for LMStudioClient used by the API tests."""

    models: list[ModelInfo] = [READY_MODEL]
    list_error: Exception | None = None
    load_error: Exception | None = None
    load_gate: asyncio.Event | None = None

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def list_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        if FakeClient.list_error is not None:
            raise FakeClient.list_error
        excluded = set(excluded_model_ids or [])
        return [model for model in FakeClient.models if model.id not in excluded]

    async def list_vision_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        return [model for model in await self.list_models(excluded_model_ids) if model.vision]

    async def load_and_warm_model(self, model: str, **kwargs) -> dict:
        if FakeClient.load_gate is not None:
            await FakeClient.load_gate.wait()
        if FakeClient.load_error is not None:
            raise FakeClient.load_error
        return {
            "model": model,
            "status": "ready",
            "load_ms": 1,
            "warmup_ms": 1,
            "total_ms": 2,
            "unloaded_models": 0,
            "profile": "standard",
            "already_loaded": False,
            "already_ready": False,
            "warmup_mode": "vision_and_schema",
            "preparation_attempts": 1,
        }


@pytest.fixture(autouse=True)
def isolated_api(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json")
    store.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(main, "settings_store", store)
    monkeypatch.setattr(main, "LMStudioClient", FakeClient)
    main.model_runtime_states.clear()
    main.model_warmup_modes.clear()
    FakeClient.models = [READY_MODEL]
    FakeClient.list_error = None
    FakeClient.load_error = None
    FakeClient.load_gate = None
    yield store
    main.model_runtime_states.clear()
    main.model_warmup_modes.clear()


def runtime_state(client: TestClient, model_id: str) -> str:
    listed = client.get("/api/models").json()
    return next(model["runtime_state"] for model in listed if model["id"] == model_id)


def test_unexpected_load_failure_does_not_leave_the_model_stuck_loading() -> None:
    FakeClient.load_error = RuntimeError("boom")
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/models/load", json={"model": "vision-model"})
        assert response.status_code >= 500
        assert runtime_state(client, "vision-model") == "error"


def test_cancelled_load_does_not_leave_the_model_stuck_loading() -> None:
    FakeClient.load_error = asyncio.CancelledError()
    with TestClient(main.app, raise_server_exceptions=False) as client:
        client.post("/api/models/load", json={"model": "vision-model"})
        assert runtime_state(client, "vision-model") == "error"


def test_prompts_are_saved_while_lm_studio_is_unreachable(isolated_api) -> None:
    FakeClient.list_error = LMStudioError("LM Studio is not reachable")
    with TestClient(main.app) as client:
        settings = AppSettings(model="vision-model")
        settings.prompts.system_prompt = "Offline edit"
        response = client.put("/api/settings", json=settings.model_dump(mode="json"))

    assert response.status_code == 200
    assert isolated_api.read().prompts.system_prompt == "Offline edit"


def test_switching_model_while_lm_studio_is_unreachable_is_rejected(isolated_api) -> None:
    FakeClient.list_error = LMStudioError("LM Studio is not reachable")
    with TestClient(main.app) as client:
        settings = AppSettings(model="another-model")
        response = client.put("/api/settings", json=settings.model_dump(mode="json"))

    assert response.status_code == 503
    assert isolated_api.read().model == "vision-model"


def test_switching_to_an_unknown_model_is_still_rejected() -> None:
    with TestClient(main.app) as client:
        settings = AppSettings(model="not-installed")
        response = client.put("/api/settings", json=settings.model_dump(mode="json"))

    assert response.status_code == 400


async def test_a_second_model_operation_is_refused_instead_of_queued() -> None:
    FakeClient.load_gate = asyncio.Event()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = asyncio.create_task(client.post("/api/models/load", json={"model": "vision-model"}))
        await asyncio.sleep(0)
        second = await client.post("/api/models/load", json={"model": "vision-model"})

        assert second.status_code == 409
        assert not first.done()

        FakeClient.load_gate.set()
        assert (await first).status_code == 200
