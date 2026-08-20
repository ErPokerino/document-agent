"""Compare an extraction against ground truth labels.

Matching is format aware. Comparing raw strings would score a correct answer as
wrong for cosmetic reasons ("  acme  ltd" vs "ACME Ltd"), which makes the whole
metric useless for deciding whether a prompt change helped.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction


# Invoice totals are rounded to cents; anything closer than half a cent is the
# same number expressed differently.
DECIMAL_TOLERANCE = 0.005

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")


@dataclass(frozen=True)
class FieldOutcome:
    entity: str
    expected: Any
    actual: Any
    confidence: str
    matched: bool


@dataclass(frozen=True)
class Tally:
    matched: int = 0
    total: int = 0

    @property
    def accuracy(self) -> float | None:
        return self.matched / self.total if self.total else None


@dataclass(frozen=True)
class EvaluationMetrics:
    matched: int = 0
    total: int = 0
    per_entity: dict[str, Tally] = field(default_factory=dict)
    per_confidence: dict[str, Tally] = field(default_factory=dict)

    @property
    def accuracy(self) -> float | None:
        return self.matched / self.total if self.total else None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_date(value: Any) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def values_match(expected: Any, actual: Any, entity: EntityDefinition) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None

    if entity.format is EntityFormat.date:
        normalized_expected = _normalize_date(expected)
        normalized_actual = _normalize_date(actual)
        return normalized_expected is not None and normalized_expected == normalized_actual

    if entity.format is EntityFormat.currency:
        if not isinstance(expected, str) or not isinstance(actual, str):
            return False
        return expected.strip().upper() == actual.strip().upper()

    if entity.format in {EntityFormat.decimal, EntityFormat.integer}:
        # A number the model returned as unparsed text is a real failure, not a
        # formatting detail, so it is never coerced here.
        expected_number = _as_number(expected)
        actual_number = _as_number(actual)
        if expected_number is None or actual_number is None:
            return False
        return abs(expected_number - actual_number) < DECIMAL_TOLERANCE

    if not isinstance(expected, str) or not isinstance(actual, str):
        return expected == actual
    return _normalize_text(expected) == _normalize_text(actual)


def score_document(
    entities: list[EntityDefinition],
    labels: dict[str, Any],
    extraction: dict[str, FieldExtraction],
) -> list[FieldOutcome]:
    """Score one document. Entities absent from `labels` are not scored."""
    by_name = {entity.name: entity for entity in entities}
    unknown = sorted(set(labels) - set(by_name))
    if unknown:
        raise ValueError(f"The labels name entities that are not configured: {', '.join(unknown)}")

    outcomes: list[FieldOutcome] = []
    for name, expected in labels.items():
        entity = by_name[name]
        extracted = extraction.get(name)
        actual = extracted.value if extracted else None
        outcomes.append(
            FieldOutcome(
                entity=name,
                expected=expected,
                actual=actual,
                confidence=extracted.confidence if extracted else "low",
                matched=bool(extracted) and values_match(expected, actual, entity),
            )
        )
    return outcomes


def aggregate(outcomes: list[FieldOutcome]) -> EvaluationMetrics:
    per_entity: dict[str, Tally] = {}
    per_confidence: dict[str, Tally] = {}

    def bump(bucket: dict[str, Tally], key: str, matched: bool) -> None:
        current = bucket.get(key, Tally())
        bucket[key] = Tally(current.matched + int(matched), current.total + 1)

    for outcome in outcomes:
        bump(per_entity, outcome.entity, outcome.matched)
        bump(per_confidence, outcome.confidence, outcome.matched)

    return EvaluationMetrics(
        matched=sum(outcome.matched for outcome in outcomes),
        total=len(outcomes),
        per_entity=per_entity,
        per_confidence=per_confidence,
    )
