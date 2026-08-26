"""Corrections that apply to one supplier's documents and nobody else's.

Layouts repeat per supplier, and so do the exceptions: this one prefixes the
number with `Ns. Rif.`, this one always bills in euro, this one writes the date
the other way round. A general prompt cannot absorb all of that without getting
worse at everything else, so the corrections live beside the supplier and run
after it has been identified.

Keyed on `id_subject`, never on the supplier's name. Several spellings of one
supplier legitimately resolve to the same internal id, and the id is the thing
that is either right or wrong.

Two kinds of rule, deliberately. A deterministic rule — a fixed value or a
regex over what the page said — costs nothing, cannot hallucinate, and is what
most supplier exceptions actually are. A prompted rule is a second model call,
and the point of separating them is that the call is only made when there is
something to ask.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Literal

from app.domain.models import FieldExtraction


RuleKind = Literal["fixed", "regex", "prompt"]
RULE_KINDS: tuple[str, ...] = ("fixed", "regex", "prompt")


@dataclass(frozen=True)
class SupplierRule:
    id_subject: str
    entity: str
    kind: str
    # fixed
    value: str = ""
    # regex, over the document text when there is one, else the current value
    pattern: str = ""
    # prompt
    prompt: str = ""
    id: int | None = None
    note: str = ""


def rules_for(rules: list[SupplierRule], id_subject: object) -> list[SupplierRule]:
    """The rules belonging to this supplier, in the order they were written.

    A document whose supplier was not identified gets none: inheriting somebody
    else's corrections is worse than applying none at all.
    """
    identifier = str(id_subject or "").strip()
    if not identifier:
        return []
    return [rule for rule in rules if rule.id_subject == identifier]


def prompted_rules(rules: list[SupplierRule]) -> list[SupplierRule]:
    """The rules that need the model, so a call is only made when there is one."""
    return [rule for rule in rules if rule.kind == "prompt" and rule.prompt.strip()]


def apply_deterministic_rules(
    extraction: dict[str, FieldExtraction],
    rules: list[SupplierRule],
    document_text: str,
) -> tuple[dict[str, FieldExtraction], list[str]]:
    """Apply every rule that needs no model. Returns the result and what moved.

    Rules are applied in order, so a later one wins over an earlier one for the
    same field. A rule naming a field that is not configured is ignored: entities
    get renamed and removed, and a stale rule must not put a field back.
    """
    result = dict(extraction)
    changed: list[str] = []

    for rule in rules:
        if rule.entity not in result:
            continue
        current = result[rule.entity]

        if rule.kind == "fixed":
            if not rule.value.strip():
                continue
            replacement: object = rule.value
        elif rule.kind == "regex":
            replacement = _from_pattern(rule.pattern, document_text, current.value)
            if replacement is None:
                continue
        else:
            # "prompt" is handled by the caller, which decides whether the
            # second model call is worth making. Anything else is a rule kind
            # this version does not know, and is left alone.
            continue

        if replacement == current.value:
            continue
        result[rule.entity] = current.model_copy(
            update={
                "value": replacement,
                # Not a guess: a rule fired because someone wrote it for this
                # supplier, so it does not inherit the model's uncertainty.
                "confidence": "high",
                "warning": None,
            }
        )
        if rule.entity not in changed:
            changed.append(rule.entity)

    return result, changed


def _from_pattern(pattern: str, document_text: str, current: object) -> str | None:
    """What the pattern finds, in the page text or failing that in the value.

    A vision pipeline leaves no OCR text, and a rule that tidies up what the
    model read is still worth having there.
    """
    if not pattern.strip():
        return None
    try:
        expression = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except re.error:
        # A half-written pattern is a mistake in one rule, not a reason to fail
        # the document it was written for.
        return None

    for haystack in (document_text, "" if current is None else str(current)):
        if not haystack:
            continue
        match = expression.search(haystack)
        if match is None:
            continue
        captured = match.group(1) if match.groups() else match.group(0)
        if captured and captured.strip():
            return captured.strip()
    return None


# -- storage -------------------------------------------------------------------


SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    id_subject  TEXT    NOT NULL,
    entity      TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    value       TEXT    NOT NULL DEFAULT '',
    pattern     TEXT    NOT NULL DEFAULT '',
    prompt      TEXT    NOT NULL DEFAULT '',
    note        TEXT    NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS supplier_rules_subject ON supplier_rules(id_subject);
"""


class SupplierRuleStore:
    """Rules beside the register they belong to, in the same database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def all(self) -> list[SupplierRule]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM supplier_rules ORDER BY id_subject, position, id"
            ).fetchall()
        return [_row_to_rule(row) for row in rows]

    def for_supplier(self, id_subject: str) -> list[SupplierRule]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM supplier_rules WHERE id_subject = ? ORDER BY position, id",
                (id_subject,),
            ).fetchall()
        return [_row_to_rule(row) for row in rows]

    def add(self, rule: SupplierRule) -> SupplierRule:
        if rule.kind not in RULE_KINDS:
            raise ValueError(f"{rule.kind!r} is not a rule kind")
        if not rule.id_subject.strip() or not rule.entity.strip():
            raise ValueError("A rule needs a supplier and a field")
        with self._connect() as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM supplier_rules WHERE id_subject = ?",
                (rule.id_subject,),
            ).fetchone()[0]
            cursor = connection.execute(
                """
                INSERT INTO supplier_rules
                    (id_subject, entity, kind, value, pattern, prompt, note, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.id_subject, rule.entity, rule.kind,
                    rule.value, rule.pattern, rule.prompt, rule.note, position,
                ),
            )
            new_id = int(cursor.lastrowid)
        return replace(rule, id=new_id)

    def update(self, rule_id: int, values: dict[str, Any]) -> SupplierRule | None:
        allowed = {"entity", "kind", "value", "pattern", "prompt", "note"}
        fields = {key: value for key, value in values.items() if key in allowed}
        if not fields:
            return self.get(rule_id)
        if "kind" in fields and fields["kind"] not in RULE_KINDS:
            raise ValueError(f"{fields['kind']!r} is not a rule kind")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE supplier_rules SET {assignments} WHERE id = ?",
                (*fields.values(), rule_id),
            )
        return self.get(rule_id)

    def get(self, rule_id: int) -> SupplierRule | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM supplier_rules WHERE id = ?", (rule_id,)
            ).fetchone()
        return _row_to_rule(row) if row is not None else None

    def delete(self, rule_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM supplier_rules WHERE id = ?", (rule_id,))


def _row_to_rule(row: sqlite3.Row) -> SupplierRule:
    return SupplierRule(
        id=int(row["id"]),
        id_subject=row["id_subject"],
        entity=row["entity"],
        kind=row["kind"],
        value=row["value"] or "",
        pattern=row["pattern"] or "",
        prompt=row["prompt"] or "",
        note=row["note"] or "",
    )
