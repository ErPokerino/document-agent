"""LM Studio and Gemini are asked the same question, from one place."""

import json

from app.domain.models import EntityDefinition, EntityFormat, PromptConfiguration
from app.services.extraction_provider import VALUE_CHARACTER_CEILING, ExtractionProvider
from app.services.gemini import GeminiClient
from app.services.lm_studio import LMStudioClient


def entity(name: str, **overrides) -> EntityDefinition:
    return EntityDefinition.model_validate(
        {"name": name, "format": EntityFormat.text, "description": "x", **overrides}
    )


PROMPTS = PromptConfiguration(
    entities=[entity("supplier_name"), entity("id_subject", source="derived")]
)


def test_both_providers_are_extraction_providers() -> None:
    assert issubclass(LMStudioClient, ExtractionProvider)
    assert issubclass(GeminiClient, ExtractionProvider)


def test_both_providers_describe_the_same_fields() -> None:
    """Written twice, the lists drifted: Gemini kept describing derived fields."""
    lines = ExtractionProvider._entity_lines(PROMPTS)

    assert lines in LMStudioClient._system_prompt(PROMPTS)
    assert lines in GeminiClient._system_prompt(PROMPTS)
    assert "id_subject" not in lines


def test_both_providers_send_the_same_request_text() -> None:
    text = ExtractionProvider._user_text(
        PROMPTS, "1-2", total_pages=3, processed_pages=2, document_text="Invoice 42"
    )

    assert "only the first 2 are supplied here" in text
    assert text.endswith("Invoice 42")


def gemini_answer(value: str) -> dict:
    payload = {"supplier_name": value, "confidence": {"supplier_name": "high"}}
    return {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(payload)}]}}
        ]
    }


def test_a_gemini_value_past_the_ceiling_is_discarded_like_a_runaway() -> None:
    """LM Studio's grammar bounds a value; Gemini's schema cannot, so the answer is."""
    result = GeminiClient._parse(gemini_answer("ab" * VALUE_CHARACTER_CEILING), PROMPTS.entities)

    assert result["supplier_name"].value is None
    assert "ceiling" in result["supplier_name"].warning


def test_a_gemini_value_within_the_ceiling_is_kept() -> None:
    result = GeminiClient._parse(gemini_answer("ACME S.p.A."), PROMPTS.entities)

    assert result["supplier_name"].value == "ACME S.p.A."
