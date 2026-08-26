"""Extraction by Google's Custom Extractor, instead of by a language model.

The processor is asked for the fields configured in Extraction, and it answers
with a value, a confidence and the box the value sits in. Three consequences
follow, and each is the reason for a decision here.

The schema travels **with the request**, not in the processor. A generative
Custom Extractor accepts a `schemaOverride` per call, so Extraction stays the
one place fields are defined and nothing on Google's side has to be kept in
step with it.

Confidence comes from the processor, so nothing asks a model how sure it is.
A number is more use than a guessed adjective, and it is kept alongside the
band the rest of the app reads.

Boxes come with the entities, so a value's position is known exactly rather
than searched for in the page text.
"""

import pytest

from app.domain.models import EntityDefinition, EntityFormat
from app.services.custom_extractor import (
    HIGH_CONFIDENCE,
    MEDIUM_CONFIDENCE,
    confidence_band,
    entities_from_response,
    locations_from_response,
    schema_override,
)


def entity(name: str, fmt: EntityFormat = EntityFormat.text) -> EntityDefinition:
    return EntityDefinition(name=name, description=f"The {name}.", format=fmt)


ENTITIES = [
    entity("supplier_name"),
    entity("date", EntityFormat.date),
    entity("total_amount", EntityFormat.decimal),
    entity("currency", EntityFormat.currency),
]


def found(
    kind: str,
    text: str,
    confidence: float = 0.95,
    normalized: dict | None = None,
    box: tuple[float, float, float, float] | None = None,
    page: int = 0,
) -> dict:
    answer: dict = {"type": kind, "mentionText": text, "confidence": confidence}
    if normalized is not None:
        answer["normalizedValue"] = normalized
    if box is not None:
        left, top, right, bottom = box
        answer["pageAnchor"] = {
            "pageRefs": [
                {
                    "page": str(page),
                    "boundingPoly": {
                        "normalizedVertices": [
                            {"x": left, "y": top},
                            {"x": right, "y": top},
                            {"x": right, "y": bottom},
                            {"x": left, "y": bottom},
                        ]
                    },
                }
            ]
        }
    return answer


# -- what is asked for ----------------------------------------------------------


def test_the_configured_fields_travel_with_the_request() -> None:
    """Nothing on Google's side has to be edited to change what is extracted."""
    override = schema_override(ENTITIES)
    properties = override["entityTypes"][0]["properties"]
    assert [prop["name"] for prop in properties] == [
        "supplier_name", "date", "total_amount", "currency",
    ]


def test_each_field_asks_for_the_type_it_is_configured_as() -> None:
    properties = {
        prop["name"]: prop["valueType"] for prop in schema_override(ENTITIES)["entityTypes"][0]["properties"]
    }
    assert properties["supplier_name"] == "string"
    assert properties["date"] == "datetime"
    assert properties["total_amount"] == "number"
    assert properties["currency"] == "string"


def test_no_field_is_demanded_because_a_document_may_not_carry_it() -> None:
    """Required would force the processor to invent something."""
    for prop in schema_override(ENTITIES)["entityTypes"][0]["properties"]:
        assert prop["occurrenceType"] == "OPTIONAL_ONCE"


def test_a_field_a_pipeline_step_fills_is_not_asked_of_the_processor() -> None:
    derived = EntityDefinition(
        name="id_subject", description="Internal id.", format=EntityFormat.text, source="derived"
    )
    names = [
        prop["name"] for prop in schema_override([*ENTITIES, derived])["entityTypes"][0]["properties"]
    ]
    assert "id_subject" not in names


# -- what comes back ------------------------------------------------------------


def test_a_value_arrives_with_the_confidence_the_processor_gave_it() -> None:
    document = {"entities": [found("supplier_name", "ACME SUPPLIES LTD", 0.97)]}
    result = entities_from_response(document, ENTITIES)
    assert result["supplier_name"].value == "ACME SUPPLIES LTD"
    assert result["supplier_name"].confidence == "high"
    # The number is kept: it says more than the band it falls in.
    assert result["supplier_name"].score == pytest.approx(0.97)


def test_a_field_the_processor_did_not_find_is_null_and_not_omitted() -> None:
    """Every configured field comes back, so the shape never surprises a caller."""
    result = entities_from_response({"entities": []}, ENTITIES)
    assert set(result) == {"supplier_name", "date", "total_amount", "currency"}
    assert result["supplier_name"].value is None
    assert result["supplier_name"].confidence == "low"


def test_a_date_is_normalized_the_way_the_rest_of_the_app_writes_dates() -> None:
    document = {
        "entities": [
            found("date", "14/03/2024", normalized={"dateValue": {"year": 2024, "month": 3, "day": 14}})
        ]
    }
    assert entities_from_response(document, ENTITIES)["date"].value == "2024-03-14"


def test_a_date_the_processor_could_not_normalize_keeps_what_it_read() -> None:
    document = {"entities": [found("date", "14 March 2024")]}
    assert entities_from_response(document, ENTITIES)["date"].value == "14 March 2024"


def test_a_number_comes_back_as_a_number() -> None:
    document = {"entities": [found("total_amount", "1.220,00", normalized={"text": "1220.00"})]}
    assert entities_from_response(document, ENTITIES)["total_amount"].value == pytest.approx(1220.0)


def test_a_field_nobody_configured_is_ignored() -> None:
    """A processor version may return more than was asked for."""
    document = {"entities": [found("vat_number", "IT01"), found("supplier_name", "ACME")]}
    result = entities_from_response(document, ENTITIES)
    assert "vat_number" not in result


def test_the_first_answer_wins_when_a_field_comes_back_twice() -> None:
    document = {
        "entities": [found("supplier_name", "ACME", 0.9), found("supplier_name", "OTHER", 0.4)],
    }
    assert entities_from_response(document, ENTITIES)["supplier_name"].value == "ACME"


# -- how sure it was ------------------------------------------------------------


def test_the_bands_are_ordered_and_cover_everything() -> None:
    assert confidence_band(0.99) == "high"
    assert confidence_band(HIGH_CONFIDENCE) == "high"
    assert confidence_band(MEDIUM_CONFIDENCE) == "medium"
    assert confidence_band(0.1) == "low"
    assert confidence_band(None) == "low"


# -- where it was ---------------------------------------------------------------


def test_a_box_comes_back_with_the_entity_rather_than_being_searched_for() -> None:
    document = {"entities": [found("supplier_name", "ACME", box=(0.1, 0.2, 0.4, 0.24))]}
    located = locations_from_response(document, ENTITIES)
    assert len(located) == 1
    assert located[0].entity == "supplier_name"
    assert located[0].page == 0
    assert located[0].left == pytest.approx(0.1)
    assert located[0].bottom == pytest.approx(0.24)


def test_a_value_on_a_later_page_reports_that_page() -> None:
    document = {"entities": [found("supplier_name", "ACME", box=(0.1, 0.2, 0.4, 0.24), page=2)]}
    assert locations_from_response(document, ENTITIES)[0].page == 2


def test_an_entity_with_no_box_is_simply_not_located() -> None:
    document = {"entities": [found("supplier_name", "ACME")]}
    assert locations_from_response(document, ENTITIES) == []


def test_a_value_spanning_two_boxes_is_covered_by_both() -> None:
    """A name wrapped over two lines has a page ref each; one box holds them."""
    document = {
        "entities": [
            {
                "type": "supplier_name",
                "mentionText": "ACME SUPPLIES\nLIMITED",
                "confidence": 0.9,
                "pageAnchor": {
                    "pageRefs": [
                        {"page": "0", "boundingPoly": {"normalizedVertices": [
                            {"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.2},
                            {"x": 0.4, "y": 0.22}, {"x": 0.1, "y": 0.22}]}},
                        {"page": "0", "boundingPoly": {"normalizedVertices": [
                            {"x": 0.1, "y": 0.23}, {"x": 0.3, "y": 0.23},
                            {"x": 0.3, "y": 0.25}, {"x": 0.1, "y": 0.25}]}},
                    ]
                },
            }
        ]
    }
    located = locations_from_response(document, ENTITIES)[0]
    assert located.top == pytest.approx(0.2)
    assert located.bottom == pytest.approx(0.25)
    assert located.right == pytest.approx(0.4)


# -- the app's own validation applies here too -----------------------------------


def test_a_value_in_the_wrong_format_is_flagged_like_any_other() -> None:
    """The processor answered `$`; a currency is a three-letter code here.

    Validation is not the model's job or the processor's — it is the app's, and
    it has to apply whoever read the page. Otherwise one path silently accepts
    what another rejects.
    """
    from app.services.custom_extractor import validated_entities_from_response

    document = {"entities": [found("currency", "$", 1.0)]}
    result = validated_entities_from_response(document, ENTITIES)
    assert result["currency"].value is None
    assert result["currency"].warning


def test_a_value_in_the_right_format_keeps_the_processors_confidence() -> None:
    from app.services.custom_extractor import validated_entities_from_response

    document = {"entities": [found("currency", "usd", 0.93)]}
    result = validated_entities_from_response(document, ENTITIES)
    # Canonicalized by the same validation every other provider goes through.
    assert result["currency"].value == "USD"
    assert result["currency"].confidence == "high"
    assert result["currency"].score == pytest.approx(0.93)


def test_validation_does_not_lose_the_score_on_the_fields_it_leaves_alone() -> None:
    from app.services.custom_extractor import validated_entities_from_response

    document = {"entities": [found("supplier_name", "ACME LTD", 0.72)]}
    result = validated_entities_from_response(document, ENTITIES)
    assert result["supplier_name"].confidence == "medium"
    assert result["supplier_name"].score == pytest.approx(0.72)


# -- what the processor is told about each field ---------------------------------


def test_every_property_carries_the_description_the_processor_reads() -> None:
    """Measured, not assumed: with no description this processor answered `$`
    for a currency, and with one naming ISO 4217 it answered `USD`."""
    from app.services.custom_extractor import API_VERSION

    properties = {
        prop["name"]: prop["description"]
        for prop in schema_override(ENTITIES)["entityTypes"][0]["properties"]
    }
    assert "ISO 4217" in properties["currency"]
    assert "YYYY-MM-DD" in properties["date"]
    assert properties["supplier_name"].startswith("The supplier_name.")
    # A description needs the beta endpoint; v1 rejects the field.
    assert API_VERSION == "v1beta3"


def test_the_format_rider_is_the_same_one_every_other_reader_gets() -> None:
    from app.services.field_wording import described_for_reader

    properties = {
        prop["name"]: prop["description"]
        for prop in schema_override(ENTITIES)["entityTypes"][0]["properties"]
    }
    for definition in ENTITIES:
        assert properties[definition.name] == described_for_reader(definition)
