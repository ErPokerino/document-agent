"""Rules the user writes, applied to single fields after the model has answered.

Deliberately narrow. A rule touches one entity, either rewriting what the model
returned or pulling a value out of the document text when the model returned
nothing. The result goes through the same validation as a model answer, so a
rule cannot slip a value past the format checks that a model could not.
"""

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.models import EntityDefinition, FieldExtraction
from app.services.field_validation import parse_named_value, validate_result


class RuleSource(str, Enum):
    value = "value"
    text = "text"


class RuleWhen(str, Enum):
    always = "always"
    if_empty = "if_empty"
    if_low_confidence = "if_low_confidence"


class RegexRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    pattern: str
    # Either take a capture group out of the match, or substitute across it.
    group: int | None = None
    replacement: str = ""
    source: RuleSource = RuleSource.value
    when: RuleWhen = RuleWhen.always
    note: str = Field(default="", max_length=200)

    @field_validator("pattern")
    @classmethod
    def pattern_compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"Not a usable regular expression: {exc}") from exc
        return value


def _applies(field: FieldExtraction, when: RuleWhen) -> bool:
    if when is RuleWhen.always:
        return True
    if when is RuleWhen.if_empty:
        return field.value is None or str(field.value).strip() == ""
    return field.confidence == "low"


def apply_rules(
    entities: list[EntityDefinition],
    extraction: dict[str, FieldExtraction],
    rules: list[RegexRule],
    text: str | None,
) -> dict[str, FieldExtraction]:
    if not rules:
        return extraction

    by_name = {entity.name: entity for entity in entities}
    working: dict[str, Any] = {
        name: {"value": field.value, "confidence": field.confidence}
        for name, field in extraction.items()
    }
    touched: set[str] = set()

    for rule in rules:
        if rule.entity not in by_name or rule.entity not in working:
            continue
        current = FieldExtraction.model_validate(working[rule.entity])
        if not _applies(current, rule.when):
            continue

        if rule.source is RuleSource.text:
            # No step produced text, so there is nothing for this rule to read.
            if not text:
                continue
            subject = text
        else:
            subject = "" if current.value is None else str(current.value)

        pattern = re.compile(rule.pattern)
        if rule.group is not None:
            match = pattern.search(subject)
            if match is None:
                continue
            try:
                replaced = match.group(rule.group)
            except IndexError:
                continue
        else:
            replaced = pattern.sub(rule.replacement, subject)
            if replaced == subject and rule.source is RuleSource.value:
                continue

        # A regex can only ever produce text. Put it back through the same
        # parser a model answer goes through, so "9.0" becomes a number for a
        # decimal field and "not a number" stays text and gets rejected below.
        working[rule.entity] = {
            "value": parse_named_value(replaced, by_name[rule.entity]),
            "confidence": current.confidence,
        }
        touched.add(rule.entity)

    # Only the fields a rule actually changed are revalidated, so an untouched
    # field keeps the warning it already carried from the model.
    revalidated = validate_result(
        {name: value for name, value in working.items() if name in touched},
        [by_name[name] for name in touched if name in by_name],
    )
    return {**extraction, **revalidated}
