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
from app.services.lm_studio import LMStudioClient, VALUE_CHARACTER_CEILING


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
