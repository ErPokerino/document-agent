"""An entity says where its value comes from, and the model is only asked for its own."""

import pytest

from app.domain.models import EntityDefinition, EntityFormat, PromptConfiguration
from app.services.gemini import GeminiClient
from app.services.lm_studio import LMStudioClient


def entity(name: str, **overrides) -> EntityDefinition:
    return EntityDefinition.model_validate(
        {"name": name, "format": EntityFormat.text, "description": "x", **overrides}
    )


MIXED = PromptConfiguration(
    entities=[
        entity("supplier_name"),
        entity("id_subject", source="derived"),
        entity("total_amount", format=EntityFormat.decimal),
    ]
)


def test_an_entity_is_asked_of_the_model_unless_it_says_otherwise() -> None:
    assert entity("supplier_name").source == "model"
    assert entity("id_subject", source="derived").source == "derived"


def test_the_lm_studio_schema_leaves_derived_entities_out() -> None:
    schema = LMStudioClient("http://x")._generation_schema(MIXED.entities)

    assert "id_subject" not in schema["properties"]
    assert {"supplier_name", "total_amount"} <= set(schema["properties"])


def test_the_gemini_schema_leaves_derived_entities_out() -> None:
    schema = GeminiClient("key").generation_schema(MIXED.entities)

    assert "id_subject" not in schema["properties"]
    assert "id_subject" not in schema["required"]


def test_the_system_prompt_does_not_describe_a_field_the_model_cannot_see() -> None:
    prompt = LMStudioClient("http://x")._system_prompt(MIXED)

    assert "supplier_name" in prompt
    assert "id_subject" not in prompt


def test_a_derived_entity_is_not_expected_back_from_the_model() -> None:
    """The packed confidence string is one character per asked field."""
    payload = {"supplier_name": "ACME", "total_amount": 1.0, "c": "hh"}

    result = LMStudioClient._validate_named_result(payload, MIXED.entities)

    assert set(result) == {"supplier_name", "total_amount"}


def test_a_pipeline_can_ask_which_entities_it_must_fill_itself() -> None:
    from app.domain.models import derived_entities, model_entities

    assert [e.name for e in model_entities(MIXED.entities)] == ["supplier_name", "total_amount"]
    assert [e.name for e in derived_entities(MIXED.entities)] == ["id_subject"]
