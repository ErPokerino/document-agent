"""A ceiling on every value the model writes.

A JSON Schema sent to LM Studio becomes a grammar, and a grammar that permits
an unbounded string permits an unbounded string forever. A model too small for
the document does not produce invalid JSON — it cannot — so it stays inside an
open value and repeats until something else stops it. On this bench that was
ten minutes per document and then a timeout.

The ceiling turns that into an instant, clean failure of one field: the value
is wrong, the JSON is complete, and the run carries on. It costs nothing on a
model that was going to answer properly.
"""

from app.domain.models import EntityDefinition, EntityFormat
from app.services.lm_studio import (
    LMStudioClient,
    VALUE_CHARACTER_CEILING,
    VALUE_CHARACTERS_PER_TOKEN,
)


def schema_for(*entities: EntityDefinition) -> dict:
    return LMStudioClient._generation_schema(list(entities))


def value_schema(schema: dict, name: str) -> dict:
    """The non-null branch of one property."""
    return next(
        branch
        for branch in schema["properties"][name]["anyOf"]
        if branch.get("type") != "null"
    )


def entity(name: str, fmt: EntityFormat = EntityFormat.text) -> EntityDefinition:
    return EntityDefinition(name=name, description=f"The {name}.", format=fmt)


def test_a_free_text_value_cannot_run_on_forever() -> None:
    schema = schema_for(entity("supplier_name"))
    assert value_schema(schema, "supplier_name")["maxLength"] == VALUE_CHARACTER_CEILING


def test_the_ceiling_clears_a_real_invoice_field() -> None:
    """Long legal names are normal; the ceiling is against runaway, not length."""
    longest = "SOCIETA ITALIANA PER CONDOTTE D'ACQUA S.P.A. IN AMMINISTRAZIONE STRAORDINARIA"
    assert VALUE_CHARACTER_CEILING > len(longest)


def test_a_pattern_already_bounds_its_own_value() -> None:
    """A date or a currency code cannot run on: the pattern fixes the length."""
    schema = schema_for(entity("issued", EntityFormat.date), entity("money", EntityFormat.currency))
    assert "maxLength" not in value_schema(schema, "issued")
    assert "maxLength" not in value_schema(schema, "money")
    assert value_schema(schema, "issued")["pattern"] == "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def test_numbers_are_not_given_a_character_ceiling() -> None:
    schema = schema_for(entity("total", EntityFormat.decimal), entity("count", EntityFormat.integer))
    assert value_schema(schema, "total") == {"type": "number"}
    assert value_schema(schema, "count") == {"type": "integer"}


def test_the_confidence_string_keeps_its_exact_length() -> None:
    schema = schema_for(entity("a"), entity("b"), entity("c"))
    assert schema["properties"]["c"]["minLength"] == 3
    assert schema["properties"]["c"]["maxLength"] == 3


def test_every_entity_is_still_required_and_ordered() -> None:
    schema = schema_for(entity("a"), entity("b"))
    assert schema["required"] == ["a", "b", "c"]


def test_the_token_budget_covers_the_longest_answer_the_schema_allows() -> None:
    """The ceiling and the budget have to agree, or the ceiling does nothing.

    `max_tokens` was a flat 32 a property, written before the ceiling existed
    and a third of what one bounded free-text value can cost. Six text fields
    were enough to exhaust it while writing an answer the grammar permitted:
    cut off mid-value, which is the failure the ceiling was added to remove.
    """
    entities = [entity(f"field_{index:02d}") for index in range(6)]
    longest_legal_answer = len(entities) * (
        VALUE_CHARACTER_CEILING // VALUE_CHARACTERS_PER_TOKEN
    )

    assert LMStudioClient._output_token_budget(entities) > longest_legal_answer


def test_a_pattern_bounded_value_is_not_budgeted_as_free_text() -> None:
    """A date cannot reach the ceiling, so it must not be paid for as if it could."""
    dated = LMStudioClient._output_token_budget([entity("issued", EntityFormat.date)])
    free = LMStudioClient._output_token_budget([entity("issued")])

    assert dated < free


def test_a_derived_entity_is_not_paid_for() -> None:
    """The schema omits derived fields; the budget counted them anyway.

    Harmless while it only inflated the number, but the two are meant to
    describe the same request.
    """
    asked = entity("supplier_name")
    derived = EntityDefinition(
        name="id_subject",
        description="Worked out by a later step.",
        format=EntityFormat.text,
        source="derived",
    )

    assert LMStudioClient._output_token_budget([asked, derived]) == (
        LMStudioClient._output_token_budget([asked])
    )
