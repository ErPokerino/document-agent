import json

import pytest

from app.services.lm_studio import LMStudioClient, requires_cpu_safe_profile


def item(
    key: str,
    quantization: str = "Q4_K_M",
    size_gb: float = 1.0,
    instances: list | None = None,
    vision: bool = True,
) -> dict:
    return {
        "type": "llm",
        "key": key,
        "display_name": key,
        "quantization": {"name": quantization},
        "size_bytes": int(size_gb * 1024**3),
        "capabilities": {"vision": vision},
        "loaded_instances": instances or [],
    }


def make_items(*items: dict):
    async def fetch(self):
        return list(items)

    return fetch


def loaded(parallel: int, context_length: int = 8192) -> list:
    return [{"id": "i1", "config": {"parallel": parallel, "context_length": context_length}}]


def test_a_large_model_needs_the_cpu_safe_profile() -> None:
    assert requires_cpu_safe_profile("Q4_K_M", int(16.5 * 1024**3)) is True


def test_an_iq_quant_needs_it_even_below_the_size_threshold() -> None:
    # IQ2_XXS at 7.6 GB used to take the REST path with GPU offload still on:
    # the compatibility profile was applied by halves.
    assert requires_cpu_safe_profile("IQ2_XXS", int(7.63 * 1024**3)) is True


def test_a_small_ordinary_quant_does_not_need_it() -> None:
    assert requires_cpu_safe_profile("Q8_0", int(0.95 * 1024**3)) is False
    assert requires_cpu_safe_profile("Q5_K_S", int(1.97 * 1024**3)) is False


@pytest.mark.asyncio
async def test_a_model_loaded_by_someone_else_is_reported_as_a_profile_mismatch(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        # parallel 4 is LM Studio's default: this instance was not loaded by us.
        return [item("qwen3.8-27b@iq2_m", "IQ2_M", 10.48, loaded(parallel=4))]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.loaded is True
    assert model.requires_safe_profile is True
    assert model.profile_matches is False


@pytest.mark.asyncio
async def test_a_model_loaded_by_us_matches_the_profile(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [item("qwen3.8-27b@iq2_m", "IQ2_M", 10.48, loaded(parallel=1))]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.requires_safe_profile is True
    assert model.profile_matches is True


@pytest.mark.asyncio
async def test_a_model_that_needs_no_special_profile_always_matches(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [item("qwen3.5-0.8b", "Q8_0", 0.95, loaded(parallel=4))]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.requires_safe_profile is False
    assert model.profile_matches is True


@pytest.mark.asyncio
async def test_an_unloaded_model_is_not_a_mismatch(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [item("qwen/qwen3.8-27b", "Q4_K_M", 16.5)]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)

    model = (await client.list_vision_models())[0]

    assert model.loaded is False
    assert model.profile_matches is True


@pytest.mark.asyncio
async def test_an_iq_quant_below_the_threshold_is_loaded_through_the_cli(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    used_cli: list[str] = []

    async def fake_items():
        return [item("qwen3.8-27b@iq2_xxs", "IQ2_XXS", 7.63)]

    async def fake_cli(model: str) -> int:
        used_cli.append(model)
        return 1000

    async def fake_post(path, payload, timeout):
        raise AssertionError(f"the REST load path must not be used: {path}")

    async def fake_warmup(*args, **kwargs):
        return None

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_load_large_model_with_cli", fake_cli)
    monkeypatch.setattr(client, "_post_json", fake_post)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("qwen3.8-27b@iq2_xxs")

    assert used_cli == ["qwen3.8-27b@iq2_xxs"]
    assert result["profile"] == "compatibility"


@pytest.mark.asyncio
async def test_a_text_only_model_is_listed_and_marked_as_such(monkeypatch) -> None:
    """OCR pipelines can use a model without vision, so it has to be offered."""
    monkeypatch.setattr(
        LMStudioClient,
        "_fetch_model_items",
        make_items(
            item("vision-one", vision=True),
            item("text-one", vision=False),
        ),
    )

    listed = await LMStudioClient("http://localhost:1234").list_models()

    assert {model.id: model.vision for model in listed} == {
        "vision-one": True,
        "text-one": False,
    }


@pytest.mark.asyncio
async def test_a_text_only_model_is_warmed_up_without_an_image(monkeypatch) -> None:
    """Sending an image to a model without vision is an error, not a warm-up."""
    client = LMStudioClient("http://localhost:1234")
    monkeypatch.setattr(
        LMStudioClient, "_fetch_model_items", make_items(item("text-one", vision=False))
    )

    posted: list[dict] = []

    from app.domain.models import PromptConfiguration

    entities = PromptConfiguration().entities
    answer = json.dumps({entity.name: None for entity in entities} | {"c": "l" * len(entities)})

    async def fake_post(self, path, payload, timeout=None):
        posted.append(payload)
        return {"load_time_seconds": 0.1, "choices": [{"message": {"content": answer}}]}

    monkeypatch.setattr(LMStudioClient, "_post_json", fake_post)

    report = await client.load_and_warm_model("text-one")

    assert report["warmup_mode"] == "schema"
    sent_content = [message["content"] for payload in posted for message in payload.get("messages", [])]
    assert not any(
        isinstance(content, list) and any(part.get("type") == "image_url" for part in content)
        for content in sent_content
    )
