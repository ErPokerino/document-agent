"""A llama.cpp router: many models, one held at a time, loaded and warmed as LM Studio's models are."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import deps
from app.domain.models import AppSettings, EntityDefinition, PromptConfiguration
from app.services import model_server
from app.services.model_server import ModelServerClient
from app.services.settings_store import SettingsStore

ENTITIES = [EntityDefinition(name="invoice_number", format="text", description="The number")]
encode = json.dumps


class FakeRouter:
    """What llama-server answers in router mode, trimmed to what is read."""

    def __init__(self) -> None:
        self.status = {"gemma-4-e4b-it": "loaded", "minicpm5-1b": "unloaded", "qwen3-vl-4b": "unloaded"}
        self.loads: list[str] = []
        self.chats: list[dict] = []
        self.polls_before_loaded = 2
        self.text_answer = "OK"

    async def get(self, url: str) -> httpx.Response:
        if url.endswith("/models") and not url.endswith("/v1/models"):
            if "loading" in self.status.values():
                if self.polls_before_loaded:
                    self.polls_before_loaded -= 1
                else:
                    self.status = {model: "loaded" if value == "loading" else value for model, value in self.status.items()}
            return httpx.Response(200, json={"data": [
                {
                    "id": model,
                    "path": f"/models/{model}.gguf",
                    "status": {"value": value, **({"args": ["llama-server", "--ctx-size", "8192", "--parallel", "1"]} if value == "loaded" else {})},
                    "architecture": {"input_modalities": ["text"] if model == "minicpm5-1b" else ["text", "image"]},
                }
                for model, value in self.status.items()
            ]})
        loaded = [model for model, value in self.status.items() if value == "loaded"]
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": model, "meta": {"n_ctx": 8192, "n_params": 7518069290, "size": 5319465128, "ftype": "Q4_K - Medium"}}
            for model in loaded
        ]})

    async def post(self, url: str, payload: dict) -> httpx.Response:
        if url.endswith("/models/unload"):
            self.status[payload["model"]] = "unloaded"
            return httpx.Response(200, json={"success": True})
        if url.endswith("/models/load"):
            self.loads.append(payload["model"])
            # --models-max 1: the model held so far is let go.
            self.status = {model: "unloaded" if value == "loaded" else value for model, value in self.status.items()}
            self.status[payload["model"]] = "loading"
            return httpx.Response(200, json={"success": True})
        self.chats.append(payload)
        content = encode({"invoice_number": None, "c": "l"}) if "response_format" in payload else self.text_answer
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]},
            request=httpx.Request("POST", url),
        )


@pytest.fixture
def router(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_URL", "https://llm.example")
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_AUTH", "none")
    catalog = tmp_path / "models.json"
    catalog.write_text(
        encode({"minicpm5-1b": {"parameters": "1B", "quantization": "Q8_0", "size_bytes": 1148846080, "vision": False}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCUFLOW_MODEL_SERVER_CATALOG", str(catalog))
    monkeypatch.setattr(model_server, "LOAD_POLL_SECONDS", 0)
    fake = FakeRouter()

    async def get(client, url, headers=None, **_):
        return await fake.get(url)

    async def post(client, url, json=None, headers=None, **_):
        return await fake.post(url, json)

    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return fake


@pytest.mark.asyncio
async def test_every_model_is_listed_with_whether_it_is_loaded(router) -> None:
    models = {model.id: model for model in await ModelServerClient().list_models()}

    assert set(models) == {"gemma-4-e4b-it", "minicpm5-1b", "qwen3-vl-4b"}
    assert (models["gemma-4-e4b-it"].runtime_state, models["gemma-4-e4b-it"].ready) == ("ready", True)
    assert (models["minicpm5-1b"].runtime_state, models["minicpm5-1b"].ready) == ("not_loaded", False)
    # What the server reports about the model it holds...
    gemma = models["gemma-4-e4b-it"]
    assert (gemma.context_length, gemma.parallel, gemma.quantization) == (8192, 1, "Q4_K_M")
    # ...and what the deployment's catalog says about one it does not.
    small = models["minicpm5-1b"]
    assert (small.parameters, small.quantization, small.size_bytes) == ("1B", "Q8_0", 1148846080)
    assert small.capabilities_known and not small.vision
    assert models["qwen3-vl-4b"].vision


@pytest.mark.asyncio
async def test_loading_waits_for_the_model_and_warms_it_as_lm_studio_does(router) -> None:
    phases: list[str] = []
    report = await ModelServerClient().load_and_warm_model(
        "qwen3-vl-4b", entities=ENTITIES, warm_vision=True, phase_callback=phases.append,
    )

    assert router.loads == ["qwen3-vl-4b"]
    assert phases == ["loading", "warming_up"]
    assert (report["profile"], report["warmup_mode"], report["unloaded_models"], report["already_ready"]) == (
        "server", "vision_and_schema", 1, False,
    )
    # The schema warm-up asked the loaded model, by name.
    assert any("response_format" in chat and chat["model"] == "qwen3-vl-4b" for chat in router.chats)
    assert router.status == {"gemma-4-e4b-it": "unloaded", "minicpm5-1b": "unloaded", "qwen3-vl-4b": "loaded"}


@pytest.mark.asyncio
async def test_a_model_already_held_is_not_loaded_again(router) -> None:
    report = await ModelServerClient().load_and_warm_model("gemma-4-e4b-it", entities=ENTITIES)

    assert router.loads == []
    assert report["already_ready"] is True


@pytest.mark.asyncio
async def test_a_run_on_a_model_the_server_does_not_hold_is_refused_until_it_is_loaded(router) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refused:
        await deps.ensure_model_ready(AppSettings(provider="model_server", model="minicpm5-1b"))
    assert refused.value.status_code == 409
    assert "Load & warm up" in refused.value.detail
    assert (await deps.ensure_model_ready(AppSettings(provider="model_server", model="gemma-4-e4b-it"))).id == "gemma-4-e4b-it"


def test_load_in_llm_loads_on_the_server_and_selects_the_model(router, tmp_path, monkeypatch) -> None:
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(provider="model_server", model="gemma-4-e4b-it", prompts=PromptConfiguration(entities=ENTITIES)))
    monkeypatch.setattr(deps, "settings_store", settings)

    answer = TestClient(main.app).post("/api/models/load", json={"model": "minicpm5-1b"})

    assert answer.status_code == 200, answer.text
    assert answer.json()["profile"] == "server"
    assert router.loads == ["minicpm5-1b"]
    assert (settings.read().provider, settings.read().model) == ("model_server", "minicpm5-1b")


@pytest.mark.asyncio
async def test_a_model_that_fails_its_warm_up_is_unloaded_rather_than_left_ready(router) -> None:
    """A runtime that does not really support a model answers garbage; the check catches it."""
    router.text_answer = "garbled"

    with pytest.raises(model_server.LMStudioError, match="warm-up"):
        await ModelServerClient().load_and_warm_model("minicpm5-1b", entities=ENTITIES, warm_vision=False)

    assert router.status["minicpm5-1b"] == "unloaded"
