"""When a step read the document, the model must be given what it read."""

import pytest

from app.domain.models import PromptConfiguration
from app.services.gemini import GeminiClient
from app.services.lm_studio import LMStudioClient


ANSWER = {
    entity.name: None for entity in PromptConfiguration().entities
} | {"c": "l" * len(PromptConfiguration().entities)}


def fake_http(monkeypatch, module: str, body: dict) -> list[dict]:
    """Capture the payload the client would have sent, and answer for it."""
    sent: list[dict] = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json():
            return body

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            sent.append(json)
            return FakeResponse()

    monkeypatch.setattr(f"app.services.{module}.httpx.AsyncClient", FakeClient)
    return sent


def captured_lm_studio(monkeypatch) -> list[dict]:
    import json

    return fake_http(
        monkeypatch,
        "lm_studio",
        {"choices": [{"message": {"content": json.dumps(ANSWER)}}]},
    )


@pytest.mark.asyncio
async def test_lm_studio_is_given_the_text_a_previous_step_read(monkeypatch) -> None:
    sent = captured_lm_studio(monkeypatch)

    await LMStudioClient("http://localhost:1234").extract_entities(
        "m", [], PromptConfiguration(), "1", total_pages=1, processed_pages=1,
        document_text="ACME LTD\nInvoice FE02",
    )

    text = "".join(
        part["text"]
        for message in sent[0]["messages"]
        for part in (message["content"] if isinstance(message["content"], list) else [])
        if part.get("type") == "text"
    )
    assert "ACME LTD" in text
    assert "Invoice FE02" in text


@pytest.mark.asyncio
async def test_lm_studio_says_nothing_about_text_when_there_was_none(monkeypatch) -> None:
    sent = captured_lm_studio(monkeypatch)

    await LMStudioClient("http://localhost:1234").extract_entities(
        "m", ["aW1n"], PromptConfiguration(), "1", total_pages=1, processed_pages=1,
    )

    text = "".join(
        part["text"]
        for message in sent[0]["messages"]
        for part in (message["content"] if isinstance(message["content"], list) else [])
        if part.get("type") == "text"
    )
    assert "extracted from the document" not in text.lower()


@pytest.mark.asyncio
async def test_gemini_is_given_the_text_a_previous_step_read(monkeypatch) -> None:
    import json

    sent = fake_http(
        monkeypatch,
        "gemini",
        {
            "candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER)}]}}],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
        },
    )

    await GeminiClient("key").extract_entities(
        "gemini-3.5-flash-lite", [], PromptConfiguration(), "1",
        total_pages=1, processed_pages=1, document_text="ACME LTD",
    )

    parts = sent[0]["contents"][0]["parts"]
    assert any("ACME LTD" in part.get("text", "") for part in parts)
