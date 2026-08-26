"""Turn whatever a model returned into validated FieldExtraction values.

Shared by every provider. One bad value is cleared and marked for review rather
than discarding the whole document, and a number the model returned as text is
a real failure, not something to coerce quietly.
"""

import re
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction


def parse_named_value(value: Any, entity: EntityDefinition) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if entity.format is EntityFormat.decimal:
        if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", normalized):
            return float(normalized)
        return normalized
    if entity.format is EntityFormat.integer:
        if re.fullmatch(r"[+-]?\d+", normalized):
            return int(normalized)
        return normalized
    return normalized

# Symbols that name exactly one currency. A bare "$" is deliberately absent:
# it is the dollar of a dozen countries, and a wrong currency on an invoice is
# worse than an empty one.
UNAMBIGUOUS_SYMBOLS = {
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₽": "RUB",
    "₩": "KRW",
    "₺": "TRY",
    "₪": "ILS",
    "S$": "SGD",
    "A$": "AUD",
    "C$": "CAD",
    "HK$": "HKD",
    "NZ$": "NZD",
    "NT$": "TWD",
    "R$": "BRL",
    "US$": "USD",
    "CHF": "CHF",
    "R₱": "PHP",
}


def validate_result(
    payload: Any,
    entities: list[EntityDefinition],
) -> dict[str, FieldExtraction]:
    if not isinstance(payload, dict):
        raise ValueError("The response is not a JSON object")

    result: dict[str, FieldExtraction] = {}
    for entity in entities:
        raw_field = payload.get(entity.name)
        if raw_field is None:
            result[entity.name] = FieldExtraction(
                value=None,
                confidence="low",
                warning="The model did not return this field.",
            )
            continue
        try:
            result[entity.name] = normalize_field(raw_field, entity)
        except (ValidationError, ValueError) as exc:
            raw_value = raw_field.get("value") if isinstance(raw_field, dict) else raw_field
            preview = repr(raw_value)
            if len(preview) > 80:
                preview = f"{preview[:77]}..."
            result[entity.name] = FieldExtraction(
                value=None,
                confidence="low",
                warning=f"Model value {preview} was discarded: {exc}.",
            )
    return result

def normalize_field(payload: Any, entity: EntityDefinition) -> FieldExtraction:
    field = FieldExtraction.model_validate(payload)
    value = field.value
    if value is None:
        return FieldExtraction(value=None, confidence="low")
    if entity.format is EntityFormat.text:
        if not isinstance(value, str):
            raise ValueError("expected text")
        return field
    if entity.format is EntityFormat.date:
        if not isinstance(value, str):
            raise ValueError("expected a YYYY-MM-DD date")
        return FieldExtraction(
            value=normalize_date(value),
            confidence=field.confidence,
        )
    if entity.format is EntityFormat.currency:
        if not isinstance(value, str):
            raise ValueError("expected an ISO 4217 currency code")
        normalized_currency = value.strip().upper()
        # Documents print symbols, not codes, and a reader that points at the
        # page can only answer with what is there. A symbol belonging to one
        # currency is that currency; a bare $ belongs to a dozen, and choosing
        # between them would be a guess dressed as a reading.
        normalized_currency = UNAMBIGUOUS_SYMBOLS.get(normalized_currency, normalized_currency)
        if not re.fullmatch(r"[A-Z]{3}", normalized_currency):
            raise ValueError("expected an ISO 4217 currency code")
        return FieldExtraction(value=normalized_currency, confidence=field.confidence)
    if entity.format is EntityFormat.decimal:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("expected a decimal number")
        return FieldExtraction(value=float(value), confidence=field.confidence)
    if entity.format is EntityFormat.integer:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("expected an integer")
    return field

def normalize_date(value: str) -> str:
    cleaned = value.strip()
    formats = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")
    for date_format in formats:
        try:
            day = date.fromisoformat(cleaned) if date_format == "%Y-%m-%d" else None
            if day is None:
                day = datetime.strptime(cleaned, date_format).date()
            return day.isoformat()
        except ValueError:
            continue
    raise ValueError("The date format is not recognized")
