import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, FieldExtraction, ModelInfo
from app.evaluation.datasets import DatasetStore
from app.evaluation.store import EvaluationStore
from app.services.lm_studio import LMStudioError
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore


LOCAL_MODEL = ModelInfo(id="vision-model", name="Vision Model", loaded=True)


class FakeLMStudio:
    error: Exception | None = None

    def __init__(self, base_url: str) -> None:
        pass

    async def list_vision_models(self, excluded_model_ids=None):
        if FakeLMStudio.error is not None:
            raise FakeLMStudio.error
        return [LOCAL_MODEL]


def pdf_bytes() -> bytes:
    import pymupdf

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Invoice")
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json")
    store.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(main, "settings_store", store)
    monkeypatch.setattr(main, "run_store", RunStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(main, "evaluation_store", EvaluationStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(main, "dataset_store", DatasetStore(tmp_path / "datasets"))
    monkeypatch.setattr(main, "LMStudioClient", FakeLMStudio)
    FakeLMStudio.error = None
    main.model_runtime_states.clear()
    main.release_model_operation()
    with TestClient(main.app) as client:
        yield client, store
    main.model_runtime_states.clear()
    main.release_model_operation()


def set_key(store: SettingsStore, key: str) -> None:
    settings = store.read()
    settings.gemini.api_key = key
    store.write(settings)


def save(api, **changes):
    client, store = api
    settings = store.read().model_copy(update=changes)
    return client.put("/api/settings", json=settings.model_dump(mode="json"))


def hosted(listed: list[dict]) -> list[dict]:
    return [model for model in listed if model["provider"] == "gemini"]


def test_hosted_models_are_listed_next_to_the_local_ones(api) -> None:
    client, _ = api

    listed = client.get("/api/models").json()

    assert {model["provider"] for model in listed} == {"lm_studio", "gemini"}
    assert "gemini-3.7-flash" in [model["id"] for model in listed]


def test_hosted_models_are_still_listed_when_lm_studio_is_down(api) -> None:
    client, _ = api
    FakeLMStudio.error = LMStudioError("LM Studio is not reachable")

    listed = client.get("/api/models").json()

    # One provider being unreachable must not hide the other.
    assert listed and all(model["provider"] == "gemini" for model in listed)


def test_a_hosted_model_is_ready_once_a_key_is_configured(api) -> None:
    client, store = api
    assert not any(model["ready"] for model in hosted(client.get("/api/models").json()))

    set_key(store, "k")

    listed = hosted(client.get("/api/models").json())
    assert all(model["ready"] for model in listed)
    assert all(model["runtime_state"] == "ready" for model in listed)


def test_the_api_key_is_never_returned_to_the_client(api) -> None:
    client, store = api
    set_key(store, "super-secret-1234")

    body = client.get("/api/settings").json()

    assert body["gemini"]["api_key"] == ""
    assert "super-secret" not in str(body)


def test_the_key_hint_says_a_key_is_configured(api) -> None:
    client, store = api
    set_key(store, "super-secret-1234")

    status = client.get("/api/settings/gemini").json()

    assert status["configured"] is True
    assert status["hint"].endswith("1234")
    assert "super-secret" not in status["hint"]


def test_no_key_configured_reports_that(api) -> None:
    client, _ = api

    status = client.get("/api/settings/gemini").json()

    assert status["configured"] is False
    assert status["hint"] == ""


def test_saving_settings_without_a_key_keeps_the_stored_one(api) -> None:
    client, store = api
    set_key(store, "keep-me")

    response = save(api, max_pages_to_analyze=4)

    assert response.status_code == 200
    assert store.read().gemini.api_key == "keep-me"
    assert store.read().max_pages_to_analyze == 4


def test_sending_a_new_key_replaces_the_stored_one(api) -> None:
    client, store = api
    settings = store.read()
    settings.gemini.api_key = "brand-new"

    assert client.put("/api/settings", json=settings.model_dump(mode="json")).status_code == 200
    assert store.read().gemini.api_key == "brand-new"


def test_the_key_can_be_removed_explicitly(api) -> None:
    client, store = api
    set_key(store, "k")

    assert client.delete("/api/settings/gemini").status_code == 204
    assert store.read().gemini.api_key == ""


def test_switching_to_a_hosted_model_does_not_need_lm_studio(api) -> None:
    FakeLMStudio.error = LMStudioError("LM Studio is not reachable")

    assert save(api, provider="gemini", model="gemini-3.7-flash").status_code == 200


def test_an_unknown_hosted_model_is_rejected(api) -> None:
    assert save(api, provider="gemini", model="gemini-9-ultra").status_code == 400


def test_a_hosted_model_cannot_be_loaded(api) -> None:
    client, _ = api

    response = client.post("/api/models/load", json={"model": "gemini-3.7-flash"})

    assert response.status_code == 400
    assert "does not need loading" in response.json()["detail"]


def test_extracting_with_a_hosted_model_needs_a_key_not_a_warm_up(api) -> None:
    client, _ = api
    save(api, provider="gemini", model="gemini-3.7-flash")

    response = client.post(
        "/api/documents/extract",
        files={"file": ("invoice.pdf", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 409
    assert "API key" in response.json()["detail"]


class FakeGemini:
    stats: dict | None = {"prompt_tokens": 1000, "completion_tokens": 50}

    def __init__(self, api_key, thinking_level="low") -> None:
        self.last_prediction_stats = FakeGemini.stats

    async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages):
        return {entity.name: FieldExtraction(value=None, confidence="low") for entity in prompts.entities}


def test_a_hosted_extraction_runs_without_any_warm_up(api, monkeypatch) -> None:
    client, store = api
    save(api, provider="gemini", model="gemini-3.7-flash")
    set_key(store, "k")
    monkeypatch.setattr("app.pipeline.steps.GeminiClient", FakeGemini)

    response = client.post(
        "/api/documents/extract",
        files={"file": ("invoice.pdf", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gemini-3.7-flash"
    assert body["processing"]["prompt_tokens"] == 1000


def test_a_run_records_which_provider_produced_it(api, monkeypatch) -> None:
    client, store = api
    save(api, provider="gemini", model="gemini-3.7-flash")
    set_key(store, "k")
    monkeypatch.setattr("app.pipeline.steps.GeminiClient", FakeGemini)

    client.post("/api/documents/extract", files={"file": ("a.pdf", pdf_bytes(), "application/pdf")})

    assert main.run_store.list_runs()[0].provider == "gemini"


def test_verifying_the_key_reports_the_models_it_can_see(api, monkeypatch) -> None:
    client, store = api
    set_key(store, "k")

    class FakeGeminiClient:
        def __init__(self, api_key, thinking_level="low") -> None:
            pass

        async def list_models(self):
            return ["gemini-3.7-flash", "gemini-9-ultra"]

    monkeypatch.setattr(main, "GeminiClient", FakeGeminiClient)

    status = client.post("/api/settings/gemini/verify").json()

    assert status["configured"] is True
    # Only the models this app is set up for are reported back.
    assert status["verified_models"] == ["gemini-3.7-flash"]


def test_verifying_without_a_key_is_refused(api) -> None:
    client, _ = api

    assert client.post("/api/settings/gemini/verify").status_code == 400
