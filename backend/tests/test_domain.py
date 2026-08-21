import base64
import json
import struct

import pytest
from pydantic import ValidationError

from app.domain.models import (
    AppSettings,
    EntityDefinition,
    EntityFormat,
    PromptConfiguration,
    default_entities,
)
from app.services.field_validation import validate_result
from app.services.lm_studio import LMStudioClient, LMStudioError, _representative_warmup_image


def test_default_invoice_entities_are_present() -> None:
    assert [entity.name for entity in default_entities()] == [
        "date",
        "document_number",
        "supplier_name",
        "currency",
        "total_amount",
    ]


def test_default_processing_limits_are_explicit() -> None:
    settings = AppSettings()
    assert settings.max_pages_to_analyze == 10
    assert settings.excluded_model_ids == []


def test_entity_names_must_be_unique() -> None:
    duplicate = EntityDefinition(name="date", format=EntityFormat.date, description="A date")
    with pytest.raises(ValidationError, match="unique"):
        PromptConfiguration(entities=[duplicate, duplicate])


def test_dynamic_generation_schema_uses_flat_named_values() -> None:
    entities = default_entities()
    schema = LMStudioClient._generation_schema(entities)
    assert schema["required"] == [
        "date",
        "document_number",
        "supplier_name",
        "currency",
        "total_amount",
        "c",
    ]
    assert schema["properties"]["total_amount"]["anyOf"] == [
        {"type": "number"},
        {"type": "null"},
    ]
    assert "Final invoice total" in schema["properties"]["total_amount"]["description"]
    assert schema["properties"]["date"]["anyOf"][0]["pattern"] == "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
    assert schema["properties"]["currency"]["anyOf"][0]["pattern"] == "^[A-Z]{3}$"
    assert schema["properties"]["c"]["pattern"] == "^[lmh]{5}$"
    # Enough room for every key, its value and the surrounding JSON punctuation.
    assert LMStudioClient._output_token_budget(entities) >= 32 * len(entities)


def test_named_result_is_expanded_to_public_field_shape() -> None:
    result = LMStudioClient._validate_named_result(
        {
            "date": "2026-07-31",
            "document_number": "INV-7",
            "supplier_name": "Example Ltd",
            "currency": "EUR",
            "total_amount": 125.31,
            "c": "hmhhm",
        },
        default_entities(),
    )
    assert result["date"].value == "2026-07-31"
    assert result["document_number"].confidence == "medium"
    assert result["total_amount"].value == 125.31


def test_native_lm_studio_stats_are_normalized() -> None:
    stats = LMStudioClient._prediction_stats(
        {
            "usage": {"prompt_tokens": 1309, "completion_tokens": 87},
            "stats": {
                "time_to_first_token": 9.405,
                "generation_time": 7.059,
                "tokens_per_second": 12.324,
                "stop_reason": "eosFound",
            },
        }
    )
    assert stats == {
        "time_to_first_token_seconds": 9.405,
        "prediction_time_seconds": 7.059,
        "tokens_per_second": 12.324,
        "prompt_tokens": 1309,
        "completion_tokens": 87,
    }


def test_warmup_image_uses_document_scale() -> None:
    png = base64.b64decode(_representative_warmup_image())
    assert png.startswith(b"\x89PNG")
    assert struct.unpack(">II", png[16:24]) == (842, 1191)


@pytest.mark.asyncio
async def test_warmup_uses_the_configured_extraction_schema(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    entities = default_entities()
    captured: list[dict] = []
    response_payload = {
        **{entity.name: None for entity in entities},
        "c": "l" * len(entities),
    }

    async def fake_post(path, payload, timeout):
        captured.append(payload)
        content = "OK" if len(captured) == 1 else json.dumps(response_payload)
        return {
            "choices": [
                {"message": {"content": content}}
            ]
        }

    monkeypatch.setattr(client, "_post_json", fake_post)

    await client._warm_up_structured_output("target", entities)

    assert len(captured) == 2
    assert captured[0]["messages"][1]["content"][1]["type"] == "image_url"
    assert "response_format" not in captured[0]
    assert captured[0]["max_tokens"] == 1
    schema = captured[1]["response_format"]["json_schema"]["schema"]
    assert schema["required"] == [
        "date",
        "document_number",
        "supplier_name",
        "currency",
        "total_amount",
        "c",
    ]
    assert captured[1]["max_tokens"] == LMStudioClient._output_token_budget(entities)
    assert isinstance(captured[1]["messages"][1]["content"], str)


def test_result_validation_normalizes_decimal() -> None:
    payload = {
        "date": {"value": "2026-08-18", "confidence": "high"},
        "document_number": {"value": "INV-42", "confidence": "high"},
        "supplier_name": {"value": "Example S.p.A.", "confidence": "medium"},
        "currency": {"value": "EUR", "confidence": "high"},
        "total_amount": {"value": 122, "confidence": "high"},
    }
    result = validate_result(payload, default_entities())
    assert result["total_amount"].value == 122.0
    assert result["supplier_name"].confidence == "medium"


def test_null_value_always_has_low_confidence() -> None:
    entity = EntityDefinition(name="reference", format=EntityFormat.text, description="Reference")
    result = validate_result(
        {"reference": {"value": None, "confidence": "high"}},
        [entity],
    )
    assert result["reference"].confidence == "low"


def test_invalid_currency_only_invalidates_that_field() -> None:
    entity = EntityDefinition(name="currency", format=EntityFormat.currency, description="Currency")
    result = validate_result(
        {"currency": {"value": "euro", "confidence": "medium"}},
        [entity],
    )
    assert result["currency"].value is None
    assert result["currency"].confidence == "low"
    assert "euro" in (result["currency"].warning or "")


def test_partial_validation_preserves_valid_fields() -> None:
    entities = default_entities()
    payload = {
        "date": {"value": "31/07/2026", "confidence": "high"},
        "document_number": {"value": "ZDP0566463", "confidence": "high"},
        "supplier_name": {"value": "ZircoDATA SG Holdings Pte. Ltd.", "confidence": "high"},
        "currency": {"value": "not-a-currency", "confidence": "medium"},
        "total_amount": {"value": 125.31, "confidence": "high"},
    }
    result = validate_result(payload, entities)
    assert result["date"].value == "2026-07-31"
    assert result["document_number"].value == "ZDP0566463"
    assert result["supplier_name"].value == "ZircoDATA SG Holdings Pte. Ltd."
    assert result["currency"].value is None
    assert result["currency"].warning is not None
    assert result["total_amount"].value == 125.31


def test_currency_symbol_is_not_inferred() -> None:
    entity = EntityDefinition(name="currency", format=EntityFormat.currency, description="Currency")
    result = validate_result(
        {"currency": {"value": "S$", "confidence": "high"}},
        [entity],
    )
    assert result["currency"].value is None
    assert result["currency"].confidence == "low"
    assert "S$" in (result["currency"].warning or "")


def test_lowercase_iso_currency_is_canonicalized() -> None:
    entity = EntityDefinition(name="currency", format=EntityFormat.currency, description="Currency")
    result = validate_result(
        {"currency": {"value": " sgd ", "confidence": "high"}},
        [entity],
    )
    assert result["currency"].value == "SGD"
    assert result["currency"].warning is None


@pytest.mark.asyncio
async def test_vision_models_are_sorted_by_disk_size(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [
            {"type": "llm", "key": "large", "display_name": "Large", "size_bytes": 20, "capabilities": {"vision": True}},
            {"type": "llm", "key": "small", "display_name": "Small", "size_bytes": 10, "capabilities": {"vision": True}},
        ]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    models = await client.list_vision_models()
    assert [model.id for model in models] == ["small", "large"]


@pytest.mark.asyncio
async def test_locally_excluded_vision_models_are_not_listed(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")

    async def fake_items():
        return [
            {"type": "llm", "key": "keep", "capabilities": {"vision": True}},
            {"type": "llm", "key": "exclude", "capabilities": {"vision": True}},
        ]

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    models = await client.list_vision_models(["exclude"])
    assert [model.id for model in models] == ["keep"]


@pytest.mark.asyncio
async def test_load_uses_one_conservative_vision_model(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    calls: list[tuple[str, dict]] = []

    async def fake_items():
        return [
            {"type": "llm", "key": "old", "capabilities": {"vision": True}, "loaded_instances": [{"id": "old-instance"}]},
            {"type": "llm", "key": "target", "quantization": {"name": "IQ2_M"}, "capabilities": {"vision": True}, "loaded_instances": []},
        ]

    async def fake_post(path, payload, timeout):
        calls.append((path, payload))
        return {"load_time_seconds": 1.25} if path.endswith("/load") else {}

    async def fake_cli(model):
        calls.append(("cli-gpu-off", {"model": model}))
        return 1250

    async def fake_warmup(model, entities, **kwargs):
        calls.append(("warmup", {"model": model}))

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_post_json", fake_post)
    monkeypatch.setattr(client, "_load_large_model_with_cli", fake_cli)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("target")

    assert calls[0] == ("/api/v1/models/unload", {"instance_id": "old-instance"})
    # An IQ quant goes through the CLI, which is the only path that turns GPU
    # offload off. It used to take the REST path with a payload that disabled
    # the KV cache on the GPU but left the layers there, which is the
    # configuration that raised vk::Queue::submit: ErrorDeviceLost.
    assert calls[1] == ("cli-gpu-off", {"model": "target"})
    assert not any(path.endswith("/models/load") for path, _ in calls if isinstance(path, str))
    assert calls[2] == ("warmup", {"model": "target"})
    assert result["load_ms"] == 1250
    assert result["unloaded_models"] == 1
    assert result["profile"] == "compatibility"


@pytest.mark.asyncio
async def test_already_loaded_target_is_not_reloaded(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    calls: list[tuple[str, dict]] = []

    async def fake_items():
        return [
            {"type": "llm", "key": "old", "capabilities": {"vision": True}, "loaded_instances": [{"id": "old-instance"}]},
            {
                "type": "llm",
                "key": "target",
                "quantization": {"name": "Q4_K_M"},
                "capabilities": {"vision": True},
                "loaded_instances": [{"id": "target-instance"}],
            },
        ]

    async def fake_post(path, payload, timeout):
        calls.append((path, payload))
        return {}

    async def fake_warmup(model, entities, **kwargs):
        calls.append(("warmup", {"model": model}))

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_post_json", fake_post)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("target")

    assert calls == [
        ("/api/v1/models/unload", {"instance_id": "old-instance"}),
        ("warmup", {"model": "target"}),
    ]
    assert result["already_loaded"] is True
    assert result["load_ms"] == 0


@pytest.mark.asyncio
async def test_standard_model_load_keeps_lm_studio_defaults(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    load_payload: dict = {}

    async def fake_items():
        return [
            {
                "type": "llm",
                "key": "target",
                "quantization": {"name": "Q4_K_M"},
                "capabilities": {"vision": True},
                "loaded_instances": [],
            }
        ]

    async def fake_post(path, payload, timeout):
        if path.endswith("/load"):
            load_payload.update(payload)
            return {"load_time_seconds": 1}
        return {}

    async def fake_warmup(model, entities, **kwargs):
        return None

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_post_json", fake_post)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("target")

    assert load_payload == {"model": "target", "echo_load_config": True}
    assert result["profile"] == "default"
    assert result["warmup_mode"] == "vision_and_schema"


@pytest.mark.asyncio
async def test_large_standard_model_uses_low_memory_vision_profile(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    cli_loads: list[str] = []
    warmup_options: dict = {}

    async def fake_items():
        return [
            {
                "type": "llm",
                "key": "target",
                "size_bytes": 17 * 1024**3,
                "quantization": {"name": "Q4_K_M"},
                "capabilities": {"vision": True},
                "loaded_instances": [],
            }
        ]

    async def fake_post(path, payload, timeout):
        return {}

    async def fake_cli_load(model):
        cli_loads.append(model)
        return 1250

    async def fake_warmup(model, entities, **kwargs):
        warmup_options.update(kwargs)

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_post_json", fake_post)
    monkeypatch.setattr(client, "_load_large_model_with_cli", fake_cli_load)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("target")

    assert result["profile"] == "compatibility"
    assert result["warmup_mode"] == "vision"
    assert result["load_ms"] == 1250
    assert cli_loads == ["target"]
    assert warmup_options == {"include_schema": False}


@pytest.mark.asyncio
async def test_unprepared_large_model_is_reloaded_with_cpu_safe_profile(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    calls: list[tuple[str, dict]] = []
    cli_loads: list[str] = []

    async def fake_items():
        return [
            {
                "type": "llm",
                "key": "target",
                "size_bytes": 17 * 1024**3,
                "quantization": {"name": "Q4_K_M"},
                "capabilities": {"vision": True},
                "loaded_instances": [{"id": "target-instance"}],
            }
        ]

    async def fake_post(path, payload, timeout):
        calls.append((path, payload))
        return {}

    async def fake_cli_load(model):
        cli_loads.append(model)
        return 1000

    async def fake_warmup(model, entities, **kwargs):
        return None

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_post_json", fake_post)
    monkeypatch.setattr(client, "_load_large_model_with_cli", fake_cli_load)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("target")

    assert calls == [
        ("/api/v1/models/unload", {"instance_id": "target-instance"})
    ]
    assert cli_loads == ["target"]
    assert result["already_loaded"] is False


@pytest.mark.asyncio
async def test_large_model_recovers_one_vision_startup_failure(monkeypatch) -> None:
    client = LMStudioClient("http://localhost:1234")
    warmup_calls = 0
    reloads: list[str] = []

    async def fake_items():
        return [
            {
                "type": "llm",
                "key": "target",
                "size_bytes": 17 * 1024**3,
                "capabilities": {"vision": True},
                "loaded_instances": [],
            }
        ]

    async def fake_cli_load(model):
        return 1000

    async def fake_reload(model):
        reloads.append(model)
        return 2000

    async def fake_warmup(model, entities, **kwargs):
        nonlocal warmup_calls
        warmup_calls += 1
        if warmup_calls == 1:
            raise LMStudioError(
                "LM Studio stopped while processing the document image."
            )

    monkeypatch.setattr(client, "_fetch_model_items", fake_items)
    monkeypatch.setattr(client, "_load_large_model_with_cli", fake_cli_load)
    monkeypatch.setattr(client, "_reload_large_model_with_cli", fake_reload)
    monkeypatch.setattr(client, "_warm_up_structured_output", fake_warmup)

    result = await client.load_and_warm_model("target")

    assert warmup_calls == 2
    assert reloads == ["target"]
    assert result["load_ms"] == 3000
    assert result["preparation_attempts"] == 2


def test_device_lost_error_is_actionable() -> None:
    message = LMStudioClient._friendly_engine_error(
        "vk::Queue::submit: ErrorDeviceLost",
        "Request failed",
    )
    assert "GPU/Vulkan" in message
    assert "Reload" in message


def test_terminated_error_explains_model_lifecycle() -> None:
    message = LMStudioClient._friendly_engine_error(
        '{"error":"terminated"}',
        "Request failed",
    )
    assert "unloaded, replaced" in message
    assert "ready" in message


def test_image_processing_error_recommends_low_memory_reload() -> None:
    message = LMStudioClient._friendly_engine_error(
        '{"message":"failed to process image"}',
        "Request failed",
    )
    assert "document image" in message
    assert "low-memory" in message


def test_output_token_budget_grows_with_long_entity_names() -> None:
    def entity(name: str) -> EntityDefinition:
        return EntityDefinition(name=name, format=EntityFormat.text, description="x")

    short = [entity("a")] * 1
    verbose = [entity("total_amount_including_vat_and_shipping_costs")]

    assert LMStudioClient._output_token_budget(verbose) > LMStudioClient._output_token_budget(short)


def test_output_token_budget_covers_the_maximum_entity_count() -> None:
    entities = [
        EntityDefinition(name=f"entity_number_{index:02d}", format=EntityFormat.text, description="x")
        for index in range(40)
    ]
    # A conservative floor: every key plus a short value must fit in the budget.
    assert LMStudioClient._output_token_budget(entities) >= 40 * 24


class _TruncatedResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    calls = 0
    payload: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url, json=None):
        _FakeAsyncClient.calls += 1
        return _TruncatedResponse(_FakeAsyncClient.payload)


@pytest.mark.asyncio
async def test_truncated_output_is_reported_as_an_output_limit(monkeypatch) -> None:
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.payload = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": '{"date": "2026-01-01", "document_num'},
            }
        ]
    }
    monkeypatch.setattr("app.services.lm_studio.httpx.AsyncClient", _FakeAsyncClient)
    client = LMStudioClient("http://localhost:1234")

    with pytest.raises(LMStudioError, match="output token limit"):
        await client._request_entities("model", [], default_entities())


@pytest.mark.asyncio
async def test_a_truncated_response_is_not_retried_with_a_longer_prompt(monkeypatch) -> None:
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.payload = {
        "choices": [{"finish_reason": "length", "message": {"content": '{"date": "20'}}]
    }
    monkeypatch.setattr("app.services.lm_studio.httpx.AsyncClient", _FakeAsyncClient)
    client = LMStudioClient("http://localhost:1234")

    with pytest.raises(LMStudioError):
        await client._request_entities("model", [], default_entities())

    assert _FakeAsyncClient.calls == 1


def test_runtime_crash_while_loading_is_actionable() -> None:
    # Verbatim LM Studio body when llama-server dies loading an incomplete GGUF,
    # such as a standalone MTP/draft companion file.
    detail = (
        '{"error":{"type":"model_load_failed","message":"Failed to load LLM '
        "'qwen3.8-27b-mtp': Error: Engine protocol runtime llama-server for "
        'bNrBzHg9GntfICQnLSQXF5Zn exited before becoming healthy. '
        'exitCode=3221225477, signal=null"}}'
    )

    message = LMStudioClient._friendly_engine_error(detail, "Model loading failed")

    assert "exitCode" not in message
    assert "llama-server" not in message
    assert "draft" in message.lower()


def test_an_unrecognized_engine_error_still_reports_the_raw_detail() -> None:
    message = LMStudioClient._friendly_engine_error("something unexpected", "Model loading failed")

    assert message == "Model loading failed: something unexpected"
