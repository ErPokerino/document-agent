"""The Google Cloud key: what the app says about it, and how it checks it."""

import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.services.document_ai import DocumentAiError
from app.services.settings_store import SettingsStore


class FakeLMStudio:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        return [ModelInfo(id="vision-model", name="Vision Model")]

    async def list_vision_models(self, excluded_model_ids=None):
        return [ModelInfo(id="vision-model", name="Vision Model")]


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    saved = AppSettings(model="vision-model")
    saved.gcp.project_id = "a-project"
    saved.gcp.ocr_processor_id = "ocr-id"
    saved.gcp.layout_processor_id = "layout-id"
    settings.write(saved)
    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "LMStudioClient", FakeLMStudio)
    monkeypatch.setattr(main, "GCP_CREDENTIALS_PATH", tmp_path / "gcp-service-account.json")
    with TestClient(main.app) as client:
        yield client, tmp_path


def write_key(tmp_path, **overrides) -> None:
    (tmp_path / "gcp-service-account.json").write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "a-project",
                "client_email": "docuflow@a-project.iam.gserviceaccount.com",
                "token_uri": "https://oauth2.googleapis.com/token",
                "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
                **overrides,
            }
        ),
        encoding="utf-8",
    )


def test_without_a_key_the_app_says_where_to_put_one(api) -> None:
    client, tmp_path = api

    status = client.get("/api/settings/gcp").json()

    assert status["configured"] is False
    assert "gcp-service-account.json" in status["path"]
    assert "gcp-service-account.json" in status["problem"]


def test_with_a_key_the_app_names_the_account_but_never_the_key(api) -> None:
    client, tmp_path = api
    write_key(tmp_path)

    status = client.get("/api/settings/gcp").json()

    assert status["configured"] is True
    assert status["client_email"] == "docuflow@a-project.iam.gserviceaccount.com"
    assert status["project_id"] == "a-project"
    assert "private_key" not in json.dumps(status)


def test_verifying_reports_which_processors_answered(api, monkeypatch) -> None:
    client, tmp_path = api
    write_key(tmp_path)
    asked: list[str] = []

    async def fake_process(self, processor_id, content):
        asked.append(processor_id)
        return {"document": {"text": "ok"}}

    monkeypatch.setattr("app.services.document_ai.DocumentAiClient.process", fake_process)

    status = client.post("/api/settings/gcp/verify").json()

    assert asked == ["ocr-id", "layout-id"]
    assert status["verified_processors"] == ["ocr-id", "layout-id"]
    assert status["problem"] == ""


def test_a_processor_that_refuses_is_reported_rather_than_hidden(api, monkeypatch) -> None:
    client, tmp_path = api
    write_key(tmp_path)

    async def fake_process(self, processor_id, content):
        if processor_id == "layout-id":
            raise DocumentAiError("Document AI refused processor layout-id (403). Permission denied")
        return {"document": {"text": "ok"}}

    monkeypatch.setattr("app.services.document_ai.DocumentAiClient.process", fake_process)

    status = client.post("/api/settings/gcp/verify").json()

    assert status["verified_processors"] == ["ocr-id"]
    assert "layout-id" in status["problem"]


def test_verifying_without_a_key_is_a_clear_answer_not_a_crash(api) -> None:
    client, _ = api

    status = client.post("/api/settings/gcp/verify").json()

    assert status["configured"] is False
    assert status["verified_processors"] == []
    assert "gcp-service-account.json" in status["problem"]
