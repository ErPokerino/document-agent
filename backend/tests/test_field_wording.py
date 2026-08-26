"""One wording for what a format means, shared by everything that asks.

Three readers are told what a field should look like: the Gemini schema, the
Custom Extractor's schema, and — through the prompt — a local model. They were
saying it separately, and a currency arriving as `$` from one path and `USD`
from another is what that costs.

The proof this matters is not theoretical. The same Custom Extractor answered
`$` for a currency with no description and `USD` with one that named ISO 4217.
"""

from app.domain.models import EntityDefinition, EntityFormat
from app.services.field_wording import described_for_reader


def entity(name: str, fmt: EntityFormat, description: str = "The value.") -> EntityDefinition:
    return EntityDefinition(name=name, description=description, format=fmt)


def test_a_currency_is_told_it_is_a_code_and_not_a_symbol() -> None:
    said = described_for_reader(entity("currency", EntityFormat.currency))
    assert "ISO 4217" in said
    # The failure this exists to prevent, named outright.
    assert "symbol" in said.lower()


def test_a_date_is_given_the_shape_the_app_stores() -> None:
    assert "YYYY-MM-DD" in described_for_reader(entity("date", EntityFormat.date))


def test_a_number_is_told_not_to_carry_its_punctuation() -> None:
    said = described_for_reader(entity("total", EntityFormat.decimal))
    assert "separator" in said.lower() or "thousands" in said.lower()


def test_plain_text_is_left_as_it_was_written() -> None:
    said = described_for_reader(entity("supplier_name", EntityFormat.text, "Who issued it."))
    assert said == "Who issued it."


def test_the_configured_description_always_comes_first() -> None:
    """What someone wrote about the field is the point; the format is a rider."""
    said = described_for_reader(entity("currency", EntityFormat.currency, "The billing currency."))
    assert said.startswith("The billing currency.")


def test_an_empty_description_still_carries_the_format() -> None:
    said = described_for_reader(entity("date", EntityFormat.date, " "))
    assert "YYYY-MM-DD" in said
    assert not said.startswith(" ")


# -- saying it twice is worse than saying it once ---------------------------------


def test_a_description_that_already_names_the_format_is_left_alone() -> None:
    """Measured. "Normalize it to YYYY-MM-DD." followed by "Format the value as
    YYYY-MM-DD." made the Custom Extractor return no date at all, three times
    out of three, while either sentence alone worked every time."""
    already = entity("date", EntityFormat.date, "Invoice issue date. Normalize it to YYYY-MM-DD.")
    assert described_for_reader(already) == "Invoice issue date. Normalize it to YYYY-MM-DD."


def test_the_same_holds_however_the_format_was_phrased() -> None:
    for description in ("Give it as YYYY-MM-DD.", "In yyyy-mm-dd format please."):
        said = described_for_reader(entity("date", EntityFormat.date, description))
        assert said == description


def test_a_currency_that_already_names_the_standard_is_not_told_again() -> None:
    already = entity("currency", EntityFormat.currency, "Currency of the total as an ISO 4217 code.")
    assert described_for_reader(already) == "Currency of the total as an ISO 4217 code."


def test_a_number_that_already_rules_out_separators_is_not_told_again() -> None:
    already = entity(
        "total", EntityFormat.decimal,
        "The total, as a positive number without symbols or thousands separators.",
    )
    assert described_for_reader(already).endswith("thousands separators.")


def test_a_description_that_says_nothing_about_the_format_still_gets_it() -> None:
    said = described_for_reader(entity("date", EntityFormat.date, "Invoice issue date."))
    assert "YYYY-MM-DD" in said
