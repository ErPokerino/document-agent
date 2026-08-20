import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction
from app.evaluation.scoring import aggregate, score_document


def entity(name: str, fmt: EntityFormat) -> EntityDefinition:
    return EntityDefinition(name=name, format=fmt, description="x")


ENTITIES = [
    entity("supplier_name", EntityFormat.text),
    entity("date", EntityFormat.date),
    entity("currency", EntityFormat.currency),
    entity("total_amount", EntityFormat.decimal),
]


def extraction(**values) -> dict[str, FieldExtraction]:
    return {
        name: FieldExtraction(value=value, confidence=confidence)
        for name, (value, confidence) in values.items()
    }


def test_identical_values_match() -> None:
    outcomes = score_document(
        ENTITIES,
        {"supplier_name": "ACME Ltd", "total_amount": 125.31},
        extraction(supplier_name=("ACME Ltd", "high"), total_amount=(125.31, "high")),
    )

    assert all(outcome.matched for outcome in outcomes)


def test_text_ignores_case_and_surrounding_whitespace() -> None:
    outcomes = score_document(
        [entity("supplier_name", EntityFormat.text)],
        {"supplier_name": "ACME Ltd"},
        extraction(supplier_name=("  acme   ltd ", "medium")),
    )

    assert outcomes[0].matched is True


def test_text_does_not_match_a_different_company() -> None:
    outcomes = score_document(
        [entity("supplier_name", EntityFormat.text)],
        {"supplier_name": "ACME Ltd"},
        extraction(supplier_name=("ACME Holdings", "high")),
    )

    assert outcomes[0].matched is False


def test_dates_are_compared_after_normalization() -> None:
    outcomes = score_document(
        [entity("date", EntityFormat.date)],
        {"date": "31/07/2026"},
        extraction(date=("2026-07-31", "high")),
    )

    assert outcomes[0].matched is True


def test_currency_is_case_insensitive() -> None:
    outcomes = score_document(
        [entity("currency", EntityFormat.currency)],
        {"currency": "eur"},
        extraction(currency=("EUR", "high")),
    )

    assert outcomes[0].matched is True


def test_decimals_match_within_a_cent_of_rounding() -> None:
    fields = [entity("total_amount", EntityFormat.decimal)]

    assert score_document(fields, {"total_amount": 125.31}, extraction(total_amount=(125.310001, "high")))[0].matched
    assert not score_document(fields, {"total_amount": 125.31}, extraction(total_amount=(125.4, "high")))[0].matched


def test_a_decimal_the_model_returned_as_text_does_not_match() -> None:
    outcomes = score_document(
        [entity("total_amount", EntityFormat.decimal)],
        {"total_amount": 1234.5},
        extraction(total_amount=("1.234,50", "high")),
    )

    assert outcomes[0].matched is False


def test_an_expected_null_matches_a_returned_null() -> None:
    outcomes = score_document(
        [entity("supplier_name", EntityFormat.text)],
        {"supplier_name": None},
        extraction(supplier_name=(None, "low")),
    )

    assert outcomes[0].matched is True


def test_an_expected_null_does_not_match_an_invented_value() -> None:
    outcomes = score_document(
        [entity("supplier_name", EntityFormat.text)],
        {"supplier_name": None},
        extraction(supplier_name=("ACME Ltd", "high")),
    )

    assert outcomes[0].matched is False


def test_an_unlabelled_entity_is_excluded_from_scoring() -> None:
    # A key absent from the labels means "not reviewed", which is different from
    # a key present with null, meaning "the model must return nothing here".
    outcomes = score_document(
        ENTITIES,
        {"supplier_name": "ACME Ltd"},
        extraction(
            supplier_name=("ACME Ltd", "high"),
            date=("2026-07-31", "high"),
            currency=("EUR", "high"),
            total_amount=(125.31, "high"),
        ),
    )

    assert [outcome.entity for outcome in outcomes] == ["supplier_name"]


def test_a_missing_extraction_counts_as_a_miss() -> None:
    outcomes = score_document(
        [entity("supplier_name", EntityFormat.text)],
        {"supplier_name": "ACME Ltd"},
        {},
    )

    assert outcomes[0].matched is False
    assert outcomes[0].actual is None


def test_aggregate_reports_accuracy_per_entity() -> None:
    fields = [entity("supplier_name", EntityFormat.text), entity("currency", EntityFormat.currency)]
    outcomes = [
        *score_document(fields, {"supplier_name": "A", "currency": "EUR"}, extraction(supplier_name=("A", "high"), currency=("EUR", "high"))),
        *score_document(fields, {"supplier_name": "B", "currency": "EUR"}, extraction(supplier_name=("Z", "high"), currency=("EUR", "low"))),
    ]

    metrics = aggregate(outcomes)

    assert metrics.per_entity["supplier_name"].matched == 1
    assert metrics.per_entity["supplier_name"].total == 2
    assert metrics.per_entity["supplier_name"].accuracy == 0.5
    assert metrics.per_entity["currency"].accuracy == 1.0
    assert metrics.matched == 3
    assert metrics.total == 4
    assert metrics.accuracy == 0.75


def test_aggregate_reports_how_trustworthy_each_confidence_level_is() -> None:
    fields = [entity("supplier_name", EntityFormat.text)]
    outcomes = [
        *score_document(fields, {"supplier_name": "A"}, extraction(supplier_name=("A", "high"))),
        *score_document(fields, {"supplier_name": "B"}, extraction(supplier_name=("X", "high"))),
        *score_document(fields, {"supplier_name": "C"}, extraction(supplier_name=("C", "low"))),
    ]

    metrics = aggregate(outcomes)

    # Half of what the model called "high" was wrong: that is the number that
    # tells you whether the confidence rubric is worth anything.
    assert metrics.per_confidence["high"].accuracy == 0.5
    assert metrics.per_confidence["low"].accuracy == 1.0
    assert "medium" not in metrics.per_confidence


def test_aggregate_of_nothing_is_not_a_division_by_zero() -> None:
    metrics = aggregate([])

    assert metrics.total == 0
    assert metrics.accuracy is None


def test_labels_for_an_unknown_entity_are_reported() -> None:
    with pytest.raises(ValueError, match="not_configured"):
        score_document(
            [entity("supplier_name", EntityFormat.text)],
            {"not_configured": "x"},
            extraction(supplier_name=("A", "high")),
        )
