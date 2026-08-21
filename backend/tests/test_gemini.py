import json

import pytest

from app.domain.models import EntityDefinition, EntityFormat, PromptConfiguration, default_entities
from app.services.gemini import GEMINI_MODELS, GeminiClient, GeminiError


ENTITIES = default_entities()


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status
        self.text = text or json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    """Records what the client sent and replies with a canned payload."""

    requests: list[dict] = []
    response: FakeResponse = FakeResponse({})

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url, json=None, headers=None):
        FakeAsyncClient.requests.append({"url": url, "body": json, "headers": headers or {}})
        return FakeAsyncClient.response

    async def get(self, url, headers=None):
        FakeAsyncClient.requests.append({"url": url, "headers": headers or {}})
        return FakeAsyncClient.response


def answer(values: dict, confidence: dict | None = None, usage: dict | None = None) -> FakeResponse:
    body = {
        **values,
        "confidence": confidence or {name: "high" for name in values},
    }
    return FakeResponse(
        {
            "candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}, "finishReason": "STOP"}],
            "usageMetadata": usage or {"promptTokenCount": 1200, "candidatesTokenCount": 80},
        }
    )


@pytest.fixture(autouse=True)
def fake_transport(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr("app.services.gemini.httpx.AsyncClient", FakeAsyncClient)


async def extract(client: GeminiClient, model: str = "gemini-3.7-flash"):
    return await client.extract_entities(
        model,
        ["aW1hZ2U="],
        PromptConfiguration(),
        "1",
        total_pages=1,
        processed_pages=1,
    )


def test_the_curated_models_are_the_two_we_support() -> None:
    assert [model.id for model in GEMINI_MODELS] == ["gemini-3.7-flash", "gemini-3.5-flash-lite"]


def test_the_schema_never_uses_pattern_because_gemini_rejects_it() -> None:
    schema = GeminiClient.generation_schema(ENTITIES)

    serialized = json.dumps(schema)
    assert "pattern" not in serialized


def test_type_is_a_single_proto_enum_never_a_list() -> None:
    # responseSchema is a proto Schema, not JSON Schema: `type` is a scalar
    # field. Sending ["string", "null"] returns
    # 400 Unknown name "type" ... Proto field is not repeating, cannot start list.
    schema = GeminiClient.generation_schema(ENTITIES)

    def every_type(node):
        if isinstance(node, dict):
            if "type" in node:
                yield node["type"]
            for value in node.values():
                yield from every_type(value)
        elif isinstance(node, list):
            for value in node:
                yield from every_type(value)

    assert all(isinstance(kind, str) for kind in every_type(schema))


def test_nullable_values_use_the_nullable_flag() -> None:
    schema = GeminiClient.generation_schema(ENTITIES)

    assert schema["properties"]["total_amount"]["type"] == "NUMBER"
    assert schema["properties"]["total_amount"]["nullable"] is True
    assert schema["properties"]["supplier_name"]["type"] == "STRING"
    assert schema["properties"]["supplier_name"]["nullable"] is True


def test_the_object_types_are_proto_enum_names() -> None:
    schema = GeminiClient.generation_schema(ENTITIES)

    assert schema["type"] == "OBJECT"
    assert schema["properties"]["confidence"]["type"] == "OBJECT"


def test_the_field_order_is_stated_so_generation_is_deterministic() -> None:
    schema = GeminiClient.generation_schema(ENTITIES)

    assert schema["propertyOrdering"] == [*[e.name for e in ENTITIES], "confidence"]


def test_confidence_is_an_enum_per_entity_instead_of_a_packed_string() -> None:
    schema = GeminiClient.generation_schema(ENTITIES)

    confidence = schema["properties"]["confidence"]
    assert confidence["properties"]["date"]["enum"] == ["low", "medium", "high"]
    assert confidence["properties"]["date"]["type"] == "STRING"
    assert set(confidence["required"]) == {entity.name for entity in ENTITIES}
    assert "c" not in schema["properties"]


def test_the_entity_description_reaches_the_schema() -> None:
    schema = GeminiClient.generation_schema(ENTITIES)

    assert "Final invoice total" in schema["properties"]["total_amount"]["description"]


async def test_the_api_key_travels_in_a_header_never_in_the_url() -> None:
    FakeAsyncClient.response = answer({entity.name: None for entity in ENTITIES})

    await extract(GeminiClient("secret-key"))

    request = FakeAsyncClient.requests[0]
    assert request["headers"]["x-goog-api-key"] == "secret-key"
    assert "secret-key" not in request["url"]
    assert "key=" not in request["url"]


async def test_the_request_carries_the_pages_as_inline_images() -> None:
    FakeAsyncClient.response = answer({entity.name: None for entity in ENTITIES})

    await extract(GeminiClient("k"))

    parts = FakeAsyncClient.requests[0]["body"]["contents"][0]["parts"]
    assert parts[0]["text"]
    assert parts[1]["inlineData"] == {"mimeType": "image/png", "data": "aW1hZ2U="}


async def test_the_prompt_is_sent_as_a_system_instruction() -> None:
    FakeAsyncClient.response = answer({entity.name: None for entity in ENTITIES})

    await extract(GeminiClient("k"))

    instruction = FakeAsyncClient.requests[0]["body"]["systemInstruction"]["parts"][0]["text"]
    assert "information extraction agent" in instruction


async def test_structured_output_is_requested() -> None:
    FakeAsyncClient.response = answer({entity.name: None for entity in ENTITIES})

    await extract(GeminiClient("k"))

    config = FakeAsyncClient.requests[0]["body"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["type"] == "OBJECT"
    assert config["temperature"] == 0


async def test_the_thinking_level_is_passed_for_a_model_that_supports_it() -> None:
    FakeAsyncClient.response = answer({entity.name: None for entity in ENTITIES})

    await extract(GeminiClient("k", thinking_level="low"), "gemini-3.7-flash")

    config = FakeAsyncClient.requests[0]["body"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "low"}


async def test_no_thinking_config_is_sent_to_a_model_without_thinking() -> None:
    # flash-lite has no thinking; sending the field would be rejected.
    FakeAsyncClient.response = answer({entity.name: None for entity in ENTITIES})

    await extract(GeminiClient("k", thinking_level="low"), "gemini-3.5-flash-lite")

    assert "thinkingConfig" not in FakeAsyncClient.requests[0]["body"]["generationConfig"]


async def test_the_answer_becomes_validated_fields() -> None:
    FakeAsyncClient.response = answer(
        {
            "date": "2026-07-31",
            "document_number": "INV-7",
            "supplier_name": "Example Ltd",
            "currency": "eur",
            "total_amount": 125.31,
        },
        confidence={
            "date": "high",
            "document_number": "medium",
            "supplier_name": "high",
            "currency": "low",
            "total_amount": "high",
        },
    )

    result = await extract(GeminiClient("k"))

    assert result["date"].value == "2026-07-31"
    assert result["document_number"].confidence == "medium"
    # The shared validation applies: a lowercase ISO code is canonicalized.
    assert result["currency"].value == "EUR"
    assert result["total_amount"].value == 125.31


async def test_a_bad_value_is_cleared_without_losing_the_others() -> None:
    FakeAsyncClient.response = answer(
        {
            "date": "not-a-date",
            "document_number": "INV-7",
            "supplier_name": "Example Ltd",
            "currency": "EUR",
            "total_amount": 125.31,
        }
    )

    result = await extract(GeminiClient("k"))

    assert result["date"].value is None
    assert result["date"].warning is not None
    assert result["document_number"].value == "INV-7"


async def test_token_usage_is_reported_with_thinking_counted_as_output() -> None:
    FakeAsyncClient.response = answer(
        {entity.name: None for entity in ENTITIES},
        usage={"promptTokenCount": 1500, "candidatesTokenCount": 90, "thoughtsTokenCount": 400},
    )
    client = GeminiClient("k")

    await extract(client)

    # Gemini bills thinking tokens at the output rate, so they belong there.
    assert client.last_prediction_stats["prompt_tokens"] == 1500
    assert client.last_prediction_stats["completion_tokens"] == 490
    assert client.last_prediction_stats["thinking_tokens"] == 400


async def test_a_rejected_key_is_reported_as_a_key_problem() -> None:
    FakeAsyncClient.response = FakeResponse({}, status=401, text='{"error":{"message":"API key not valid"}}')

    with pytest.raises(GeminiError, match="API key"):
        await extract(GeminiClient("wrong"))


async def test_a_rate_limit_says_so() -> None:
    FakeAsyncClient.response = FakeResponse({}, status=429, text='{"error":{"message":"Quota exceeded"}}')

    with pytest.raises(GeminiError, match="rate limit|quota"):
        await extract(GeminiClient("k"))


async def test_a_response_that_is_not_json_is_reported(monkeypatch) -> None:
    FakeAsyncClient.response = FakeResponse(
        {"candidates": [{"content": {"parts": [{"text": "sorry, no"}]}}]}
    )

    with pytest.raises(GeminiError, match="valid JSON"):
        await extract(GeminiClient("k"))


async def test_a_response_blocked_by_safety_filters_is_explained() -> None:
    FakeAsyncClient.response = FakeResponse(
        {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    )

    with pytest.raises(GeminiError, match="SAFETY"):
        await extract(GeminiClient("k"))


async def test_an_empty_api_key_never_reaches_the_network() -> None:
    with pytest.raises(GeminiError, match="API key"):
        await extract(GeminiClient(""))

    assert FakeAsyncClient.requests == []


async def test_listing_models_verifies_the_key() -> None:
    FakeAsyncClient.response = FakeResponse(
        {"models": [{"name": "models/gemini-3.7-flash"}, {"name": "models/gemini-3.5-flash-lite"}]}
    )

    available = await GeminiClient("k").list_models()

    assert available == ["gemini-3.7-flash", "gemini-3.5-flash-lite"]
    assert FakeAsyncClient.requests[0]["headers"]["x-goog-api-key"] == "k"


def test_an_integer_entity_is_typed_as_integer() -> None:
    entities = [EntityDefinition(name="pages", format=EntityFormat.integer, description="x")]

    schema = GeminiClient.generation_schema(entities)

    assert schema["properties"]["pages"]["type"] == "INTEGER"
    assert schema["properties"]["pages"]["nullable"] is True
