"""A currency symbol is a currency, when the symbol names only one.

Documents print symbols, not codes. A Singapore invoice showing `S$` was being
discarded because the app wanted three letters, while the same page read by a
person plainly says SGD.

The line drawn here is between symbols that identify one currency and symbols
that do not. `S$` is Singapore's and nobody else's; a bare `$` belongs to a
dozen countries, and guessing which would be inventing a fact about money. So
`S$` is accepted and `$` is still refused.
"""

import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction
from app.services.field_validation import validate_result


ENTITY = [EntityDefinition(name="currency", description="The currency.", format=EntityFormat.currency)]


def read(value: str):
    return validate_result({"currency": {"value": value, "confidence": "high"}}, ENTITY)["currency"]


def test_a_code_is_taken_as_it_always_was() -> None:
    assert read("usd").value == "USD"
    assert read(" EUR ").value == "EUR"


def test_a_symbol_that_belongs_to_one_currency_is_read_as_that_currency() -> None:
    assert read("S$").value == "SGD"
    assert read("€").value == "EUR"
    assert read("£").value == "GBP"
    assert read("A$").value == "AUD"
    assert read("HK$").value == "HKD"


def test_a_symbol_shared_by_many_countries_is_still_refused() -> None:
    """A bare dollar sign is a dozen currencies. Choosing one would be a guess
    dressed as a reading, and a wrong currency on an invoice is worse than
    none."""
    refused = read("$")
    assert refused.value is None
    assert refused.warning


def test_something_that_is_neither_is_refused_as_before() -> None:
    assert read("dollars").value is None
    assert read("").value is None


def test_a_symbol_is_matched_without_regard_to_spacing_or_case() -> None:
    assert read(" s$ ").value == "SGD"
