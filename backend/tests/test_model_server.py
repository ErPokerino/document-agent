"""An OpenAI-compatible model server as a provider beside LM Studio and Gemini."""

import json

encode = json.dumps

import httpx
import pytest

from app.api import deps
from app.domain.models import AppSettings, EntityDefinition, PromptConfiguration
from app.pipeline.engine import PipelineContext
from app.pipeline.steps import build_extraction_client
from app.services.model_server import ModelServerClient


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_URL", "https://llm.example/")
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_AUTH", "bearer")
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_TOKEN", "tok")
    calls = []

    async def get(self, url, headers=None, **_):
        calls.append(("GET", url, headers))
        return httpx.Response(200, json={"object": "list", "data": [{"id": "gemma-4-e4b-it"}]})

    async def post(self, url, json=None, headers=None, **_):
        calls.append(("POST", url, headers, json))
        answer = {"invoice_number": "INV-7", "c": "h"}
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": encode(answer)}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return calls


@pytest.mark.asyncio
async def test_the_server_lists_what_it_serves_as_ready(server) -> None:
    (model,) = await ModelServerClient().list_models()

    assert (model.id, model.provider, model.ready, model.capabilities_known) == ("gemma-4-e4b-it", "model_server", True, False)
    assert server[0][1] == "https://llm.example/v1/models"
    assert server[0][2] == {"Authorization": "Bearer tok"}


@pytest.mark.asyncio
async def test_extraction_goes_to_the_standard_chat_path_with_the_same_schema(server) -> None:
    prompts = PromptConfiguration(entities=[EntityDefinition(name="invoice_number", format="text", description="The number")])
    client = ModelServerClient()

    result = await client.extract_entities("gemma-4-e4b-it", [], prompts, "1", 1, 1, document_text="Invoice INV-7")
    method, url, headers, payload = next(call for call in server if call[0] == "POST")

    assert url == "https://llm.example/v1/chat/completions"
    assert headers == {"Authorization": "Bearer tok"}
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["temperature"] == 0
    assert result["invoice_number"].value == "INV-7"
    assert result["invoice_number"].confidence == "high"


def test_a_pipeline_set_to_the_model_server_is_answered_by_it(server) -> None:
    context = PipelineContext(filename="a.pdf", content=b"", model="gemma-4-e4b-it", lm_studio_url="", provider="model_server")

    assert isinstance(build_extraction_client(context), ModelServerClient)


@pytest.mark.asyncio
async def test_a_served_model_is_ready_without_loading_and_records_what_the_request_fixes(server) -> None:
    settings = AppSettings(provider="model_server", model="gemma-4-e4b-it")

    selected = await deps.ensure_model_ready(settings)
    profile = deps.execution_profile(settings, None, selected)

    assert selected.id == "gemma-4-e4b-it"
    assert (profile.provider, profile.profile, profile.temperature) == ("model_server", "server", 0)
    # How the server loaded the model is its own configuration, not claimed here.
    assert profile.context_length is None


@pytest.mark.asyncio
async def test_a_model_the_server_does_not_serve_is_refused(server) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refused:
        await deps.ensure_model_ready(AppSettings(provider="model_server", model="other"))
    assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_without_a_configured_server_nothing_is_listed(monkeypatch) -> None:
    monkeypatch.delenv("DOCUFLOW_MODEL_SERVER_URL", raising=False)

    assert await ModelServerClient().list_models() == []


def test_settings_accept_the_model_server_provider() -> None:
    assert json.loads(AppSettings(provider="model_server").model_dump_json())["provider"] == "model_server"
