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
        if url.endswith("/props"):
            # What llama.cpp's /props says, trimmed to what is read.
            return httpx.Response(200, json={"total_slots": 1, "model_path": "/models/gemma-4-E4B-it-Q4_K_M.gguf", "modalities": {"vision": True}})
        # llama.cpp's /v1/models: the OpenAI list plus its own metadata.
        return httpx.Response(200, json={
            "models": [{"model": "gemma-4-e4b-it", "capabilities": ["completion", "multimodal"]}],
            "object": "list",
            "data": [{"id": "gemma-4-e4b-it", "meta": {"n_params": 7518069290, "size": 5319465128, "n_ctx": 8192, "ftype": "Q4_K - Medium"}}],
        })

    async def post(self, url, json=None, headers=None, **_):
        calls.append(("POST", url, headers, json))
        answer = {"invoice_number": "INV-7", "c": "h"}
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": encode(answer)}}],
                "usage": {"prompt_tokens": 812, "completion_tokens": 40},
                "timings": {"predicted_ms": 2500.0, "predicted_per_second": 16.0},
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return calls


@pytest.mark.asyncio
async def test_the_server_lists_what_it_serves_as_ready(server) -> None:
    (model,) = await ModelServerClient().list_models()

    assert (model.id, model.provider, model.ready) == ("gemma-4-e4b-it", "model_server", True)
    # What the server reports about the model, as LM Studio reports it for a local one.
    assert (model.parameters, model.quantization, model.size_bytes) == ("7.5B", "Q4_K_M", 5319465128)
    assert (model.context_length, model.parallel) == (8192, 1)
    assert model.capabilities_known and model.vision
    listing = next(call for call in server if call[1] == "https://llm.example/v1/models")
    assert listing[2] == {"Authorization": "Bearer tok"}


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
    # Counted from the standard usage block, so a run's tokens are not zero.
    assert client.last_prediction_stats == {"prompt_tokens": 812, "completion_tokens": 40, "prediction_time_seconds": 2.5, "tokens_per_second": 16.0}
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
    # As the server reports it: a run records what it ran on.
    assert (profile.quantization, profile.context_length, profile.parallel) == ("Q4_K_M", 8192, 1)


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


@pytest.mark.asyncio
async def test_a_server_that_says_only_ids_is_listed_with_capabilities_unknown(monkeypatch) -> None:
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_URL", "https://llm.example")
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_AUTH", "none")

    async def get(self, url, headers=None, **_):
        if url.endswith("/props"):
            return httpx.Response(404)
        return httpx.Response(200, json={"object": "list", "data": [{"id": "some-model"}]})

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    (model,) = await ModelServerClient().list_models()

    assert model.capabilities_known is False
    assert (model.parameters, model.quantization, model.context_length) == (None, None, None)


def test_parameter_counts_and_quantizations_read_as_lm_studio_writes_them() -> None:
    from app.services.model_server import parameter_count, quantization

    assert [parameter_count(n) for n in (7_518_069_290, 800_000_000, 27_000_000_000, None)] == ["7.5B", "0.8B", "27B", None]
    assert quantization("Q4_K - Medium") == "Q4_K_M"
    assert quantization("Q8_0") == "Q8_0"
    assert quantization(None, "/models/gemma-4-E4B-it-Q4_K_M.gguf") == "Q4_K_M"
    assert quantization(None, None) is None
