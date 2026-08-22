import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction
from app.pipeline.regex_refine import RegexRule, apply_rules


ENTITIES = [
    EntityDefinition(name="document_number", format=EntityFormat.text, description="x"),
    EntityDefinition(name="total_amount", format=EntityFormat.decimal, description="x"),
]


def field(value, confidence="high"):
    return FieldExtraction(value=value, confidence=confidence)


def rule(**kwargs) -> RegexRule:
    return RegexRule.model_validate({"entity": "document_number", "pattern": "x", **kwargs})


def test_no_rules_changes_nothing() -> None:
    extraction = {"document_number": field("INV-7")}

    assert apply_rules(ENTITIES, extraction, [], text=None) == extraction


def test_a_substitution_rewrites_the_value() -> None:
    extraction = {"document_number": field("FE02 - 00028569")}

    result = apply_rules(
        ENTITIES, extraction, [rule(pattern=r"\s*-\s*", replacement="-")], text=None
    )

    assert result["document_number"].value == "FE02-00028569"


def test_a_capture_group_extracts_part_of_the_value() -> None:
    extraction = {"document_number": field("Invoice no. INV-7 / copy")}

    result = apply_rules(
        ENTITIES, extraction, [rule(pattern=r"(INV-\d+)", group=1)], text=None
    )

    assert result["document_number"].value == "INV-7"


def test_a_pattern_that_does_not_match_leaves_the_value_alone() -> None:
    extraction = {"document_number": field("INV-7")}

    result = apply_rules(ENTITIES, extraction, [rule(pattern=r"(ZZZ-\d+)", group=1)], text=None)

    assert result["document_number"].value == "INV-7"


def test_a_rule_can_be_limited_to_fields_the_model_was_unsure_about() -> None:
    extraction = {
        "document_number": field("INV-7", confidence="high"),
        "total_amount": field(1.0, confidence="low"),
    }
    rules = [
        rule(pattern=r"INV", replacement="ZZZ", when="if_low_confidence"),
        RegexRule.model_validate(
            {"entity": "total_amount", "pattern": r"1", "replacement": "9", "when": "if_low_confidence"}
        ),
    ]

    result = apply_rules(ENTITIES, extraction, rules, text=None)

    # Left alone: the model was sure about it.
    assert result["document_number"].value == "INV-7"
    assert result["total_amount"].value == 9.0


def test_a_rule_reading_the_document_text_can_fill_an_empty_field() -> None:
    extraction = {"document_number": field(None, confidence="low")}
    rules = [rule(source="text", pattern=r"Invoice\s+(INV-\d+)", group=1, when="if_empty")]

    result = apply_rules(
        ENTITIES, extraction, rules, text="Acme Ltd\nInvoice INV-42\nTotal 10"
    )

    assert result["document_number"].value == "INV-42"


def test_a_text_rule_is_skipped_when_no_step_produced_text() -> None:
    extraction = {"document_number": field(None, confidence="low")}
    rules = [rule(source="text", pattern=r"(INV-\d+)", group=1, when="if_empty")]

    result = apply_rules(ENTITIES, extraction, rules, text=None)

    assert result["document_number"].value is None


def test_a_filled_field_is_untouched_by_an_if_empty_rule() -> None:
    extraction = {"document_number": field("INV-7")}
    rules = [rule(source="text", pattern=r"(INV-\d+)", group=1, when="if_empty")]

    result = apply_rules(ENTITIES, extraction, rules, text="Invoice INV-42")

    assert result["document_number"].value == "INV-7"


def test_the_result_is_validated_against_the_entity_format() -> None:
    extraction = {"total_amount": field(125.31)}
    rules = [
        RegexRule.model_validate(
            {"entity": "total_amount", "pattern": r".*", "replacement": "not a number"}
        )
    ]

    result = apply_rules(ENTITIES, extraction, rules, text=None)

    # A rule that produces nonsense clears the field and says why, exactly as a
    # bad model answer does. It must not slip an unusable value through.
    assert result["total_amount"].value is None
    assert result["total_amount"].warning is not None


def test_a_rule_for_an_unknown_entity_is_ignored() -> None:
    extraction = {"document_number": field("INV-7")}
    rules = [RegexRule.model_validate({"entity": "nonexistent", "pattern": ".*", "replacement": "x"})]

    assert apply_rules(ENTITIES, extraction, rules, text=None)["document_number"].value == "INV-7"


def test_an_invalid_pattern_is_refused_when_the_rule_is_written() -> None:
    with pytest.raises(ValueError, match="regular expression"):
        RegexRule.model_validate({"entity": "document_number", "pattern": "([unclosed"})


def test_rules_apply_in_order() -> None:
    extraction = {"document_number": field("a")}
    rules = [
        rule(pattern="a", replacement="b"),
        rule(pattern="b", replacement="c"),
    ]

    assert apply_rules(ENTITIES, extraction, rules, text=None)["document_number"].value == "c"
