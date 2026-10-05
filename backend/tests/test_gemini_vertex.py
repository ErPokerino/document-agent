"""Gemini through Vertex AI, as the deployment's own identity: no key."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import deps
from app.domain.models import AppSettings, EntityDefinition, PromptConfiguration
from app.services import gcp_runtime
from app.services.gemini import GeminiClient, GeminiError, vertex_host
from app.services.settings_store import SettingsStore

ENTITIES = [EntityDefinition(name="invoice_number", format="text", description="The number")]
encode = json.dumps


@pytest.fixture
def vertex(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_PROJECT", "my-project")
    monkeypatch.setenv("DOCUFLOW_GEMINI_VERTEX_LOCATION", "eu")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(provider="gemini", model="gemini-3.8-flash", prompts=PromptConfiguration(entities=ENTITIES)))
    monkeypatch.setattr(deps, "settings_store", settings)

    async def token() -> str:
        return "runtime-token"

    monkeypatch.setattr(gcp_runtime, "access_token", token)
    calls = []

    async def post(client, url, json=None, headers=None, **_):
        calls.append((url, headers, json))
        if "gemini-3.1-pro-preview" in url:
            return httpx.Response(404, json={"error": {"message": "Publisher model was not found"}})
        answer = {"invoice_number": "INV-7", "confidence": {"invoice_number": "high"}}
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": encode(answer)}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return calls


def test_the_endpoint_follows_the_location() -> None:
    assert vertex_host("global") == "https://aiplatform.googleapis.com"
    assert vertex_host("eu") == "https://aiplatform.eu.rep.googleapis.com"
    assert vertex_host("europe-west4") == "https://europe-west4-aiplatform.googleapis.com"


@pytest.mark.asyncio
async def test_extraction_goes_to_vertex_as_the_runtime_identity_without_a_key(vertex) -> None:
    result = await GeminiClient("").extract_entities("gemini-3.8-flash", [], PromptConfiguration(entities=ENTITIES), "1", 1, 1, document_text="INV-7")

    url, headers, payload = vertex[0]
    assert url == "https://aiplatform.eu.rep.googleapis.com/v1/projects/my-project/locations/eu/publishers/google/models/gemini-3.8-flash:generateContent"
    assert headers["Authorization"] == "Bearer runtime-token"
    assert "x-goog-api-key" not in headers
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert result["invoice_number"].value == "INV-7"


@pytest.mark.asyncio
async def test_a_model_the_location_does_not_offer_says_so(vertex) -> None:
    with pytest.raises(GeminiError, match="location eu"):
        await GeminiClient("").extract_entities("gemini-3.1-pro-preview", [], PromptConfiguration(entities=ENTITIES), "1", 1, 1)


@pytest.mark.asyncio
async def test_hosted_models_are_ready_and_runs_allowed_without_a_key(vertex) -> None:
    settings = AppSettings(provider="gemini", model="gemini-3.8-flash")

    assert all(model.ready for model in deps.hosted_models(settings))
    assert (await deps.ensure_model_ready(settings)).id == "gemini-3.8-flash"


def test_llm_reports_vertex_and_verify_lists_the_models_this_location_offers(vertex) -> None:
    client = TestClient(main.app)

    status = client.get("/api/settings/gemini").json()
    assert (status["configured"], status["access"], status["vertex_location"]) == (True, "vertex", "eu")
    verified = client.post("/api/settings/gemini/verify").json()
    assert verified["verified_models"] == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


def test_document_ai_through_the_runtime_identity_names_the_service_account(monkeypatch) -> None:
    monkeypatch.setenv("DOCUFLOW_GCP_RUNTIME_IDENTITY", "true")
    monkeypatch.setenv("DOCUFLOW_RUNTIME_SERVICE_ACCOUNT", "docuflow-run@my-project.iam.gserviceaccount.com")

    status = TestClient(main.app).get("/api/settings/gcp").json()

    assert (status["configured"], status["access"]) == (True, "runtime_identity")
    assert status["client_email"] == "docuflow-run@my-project.iam.gserviceaccount.com"


def test_without_vertex_the_api_key_is_still_what_counts(monkeypatch) -> None:
    monkeypatch.delenv("DOCUFLOW_GEMINI_VERTEX_PROJECT", raising=False)

    assert GeminiClient("").available is False
    assert GeminiClient("key").available is True
    assert deps.key_status(AppSettings()).access == "api_key"
