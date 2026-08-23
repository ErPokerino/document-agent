"""Reference tables: the values a document implies but never states.

An invoice says "UL VS LTD"; what handles it downstream needs the internal
supplier id, which is on no page. That correspondence lives here.

One shape serves every table. A table declares its columns — which one is the
generated identifier, which may be edited, which is normalized and has to stay
unique — and the store enforces that shape for all of them. Adding a second
register is a `TableDefinition`, not another module.

Only the normalized spelling of a name is kept. The name printed on an invoice
varies between invoices from the same supplier, so storing "the" spelling would
be storing one arbitrary invoice's version of it; what identifies the supplier
is what survives normalization.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal

from app.services.similarity import normalize_company_name


class UnknownTable(LookupError):
    """No reference table is defined under that name."""


class UnknownRow(LookupError):
    """No row in that table has that identifier."""


class DuplicateRow(ValueError):
    """A row with that normalized value is already there."""


@dataclass(frozen=True)
class ColumnDefinition:
    key: str
    label: str
    hint: str = ""
    kind: Literal["identifier", "text", "timestamp"] = "text"
    editable: bool = True
    # Filled in by the store when a row is created, if nothing is supplied.
    # Generated and editable are different questions: an identifier is given
    # automatically and can still be corrected afterwards.
    generated: bool = False
    # No two rows may share the value. Normalized ones are compared after
    # normalization; an identifier is compared as typed.
    unique: bool = False
    normalized: bool = False


@dataclass(frozen=True)
class TableDefinition:
    key: str
    label: str
    description: str
    id_column: str
    id_prefix: str
    columns: tuple[ColumnDefinition, ...]
    # The labelled entity this table can be filled from, if any.
    seed_entity: str = ""
    # The column a lookup step compares against.
    match_column: str = ""

    def column(self, key: str) -> ColumnDefinition:
        for column in self.columns:
            if column.key == key:
                return column
        raise ValueError(f"{self.label} has no column {key!r}")

    @property
    def editable_columns(self) -> "tuple[ColumnDefinition, ...]":
        return tuple(column for column in self.columns if column.editable)

    @property
    def seed_column(self) -> str:
        """The column a value from a labelled document goes into."""
        if self.match_column:
            return self.match_column
        return next(column.key for column in self.editable_columns if not column.generated)


SUPPLIERS = TableDefinition(
    key="suppliers",
    label="Suppliers",
    description="Internal identifier for each supplier, matched by name.",
    id_column="id_subject",
    id_prefix="S",
    seed_entity="supplier_name",
    match_column="name",
    columns=(
        ColumnDefinition(
            key="id_subject",
            label="Id subject",
            hint=(
                "Given automatically as a running number when the row is created, and never "
                "reused. You can replace it with your own code; it has to stay unique, and "
                "documents matched under the old one keep it."
            ),
            kind="identifier",
            generated=True,
            unique=True,
        ),
        ColumnDefinition(
            key="name",
            label="Name",
            hint=(
                "Normalized as it is saved: accents folded, punctuation dropped, legal forms "
                "like S.r.l. or Ltd removed. Two suppliers cannot share one."
            ),
            unique=True,
            normalized=True,
        ),
        ColumnDefinition(
            key="source",
            label="Source",
            hint="Whether the row was typed in or filled from the labelled documents.",
            editable=False,
        ),
        ColumnDefinition(
            key="created_at",
            label="Added",
            kind="timestamp",
            editable=False,
        ),
    ),
)

TABLES: dict[str, TableDefinition] = {SUPPLIERS.key: SUPPLIERS}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MasterDataStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            for table in TABLES.values():
                columns = ", ".join(f"{column.key} TEXT" for column in table.columns)
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table.key} "
                    f"({columns}, PRIMARY KEY ({table.id_column}))"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS master_data_counters "
                "(table_key TEXT PRIMARY KEY, next INTEGER NOT NULL)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def table(key: str) -> TableDefinition:
        if key not in TABLES:
            raise UnknownTable(f"No reference table named {key!r}")
        return TABLES[key]

    def rows(
        self,
        table_key: str,
        *,
        query: str = "",
        sort: str = "",
        descending: bool = False,
        filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Rows, narrowed by a search over everything and by column.

        `query` matches any column; `filters` narrows one column each, and all
        of them apply together. Both are substring matches, case-insensitive.
        """
        table = self.table(table_key)
        order = table.column(sort).key if sort else table.id_column
        needle = f"%{query.strip().lower()}%"
        searchable = " OR ".join(f"lower({column.key}) LIKE ?" for column in table.columns)

        conditions = [f"(? = '%%' OR {searchable})"]
        parameters: list[str] = [needle, *([needle] * len(table.columns))]
        for key, value in (filters or {}).items():
            if not str(value).strip():
                continue
            conditions.append(f"lower({table.column(key).key}) LIKE ?")
            parameters.append(f"%{str(value).strip().lower()}%")

        with self._connect() as connection:
            found = connection.execute(
                f"SELECT * FROM {table.key} WHERE {' AND '.join(conditions)} "
                f"ORDER BY {order} COLLATE NOCASE {'DESC' if descending else 'ASC'}",
                tuple(parameters),
            ).fetchall()
        return [dict(row) for row in found]

    def read(self, table_key: str, identifier: str) -> dict[str, Any]:
        table = self.table(table_key)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table.key} WHERE {table.id_column} = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise UnknownRow(f"{table.label} has no row {identifier!r}")
        return dict(row)

    def add(self, table_key: str, values: dict[str, Any], source: str = "manual") -> dict[str, Any]:
        table = self.table(table_key)
        prepared = self._prepare(table, values)
        with self._connect() as connection:
            self._refuse_duplicates(connection, table, prepared)
            identifier = prepared.get(table.id_column) or self._claim_identifier(connection, table)
            row = {
                table.id_column: identifier,
                "source": source,
                "created_at": _now(),
                **prepared,
            }
            keys = [column.key for column in table.columns if column.key in row]
            connection.execute(
                f"INSERT INTO {table.key} ({', '.join(keys)}) "
                f"VALUES ({', '.join('?' for _ in keys)})",
                tuple(row[key] for key in keys),
            )
        return self.read(table_key, identifier)

    def update(self, table_key: str, identifier: str, values: dict[str, Any]) -> dict[str, Any]:
        table = self.table(table_key)
        prepared = self._prepare(table, values)
        if not prepared:
            return self.read(table_key, identifier)
        with self._connect() as connection:
            if connection.execute(
                f"SELECT 1 FROM {table.key} WHERE {table.id_column} = ?", (identifier,)
            ).fetchone() is None:
                raise UnknownRow(f"{table.label} has no row {identifier!r}")
            self._refuse_duplicates(connection, table, prepared, excluding=identifier)
            assignments = ", ".join(f"{key} = ?" for key in prepared)
            connection.execute(
                f"UPDATE {table.key} SET {assignments} WHERE {table.id_column} = ?",
                (*prepared.values(), identifier),
            )
        return self.read(table_key, prepared.get(table.id_column, identifier))

    def delete(self, table_key: str, identifier: str) -> None:
        table = self.table(table_key)
        with self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM {table.key} WHERE {table.id_column} = ?", (identifier,)
            )
            if cursor.rowcount == 0:
                raise UnknownRow(f"{table.label} has no row {identifier!r}")

    def seed(
        self,
        table_key: str,
        values: Iterable[str],
        source: str = "datasets",
    ) -> list[dict[str, Any]]:
        """Add the values not already there, and return only those.

        A value that normalizes onto an existing row is skipped rather than
        merged: whoever corrected that row knew better than this list does.
        """
        table = self.table(table_key)
        column = table.seed_column
        added: list[dict[str, Any]] = []
        for value in values:
            try:
                added.append(self.add(table_key, {column: value}, source=source))
            except (DuplicateRow, ValueError):
                continue
        return added

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _prepare(table: TableDefinition, values: dict[str, Any]) -> dict[str, str]:
        prepared: dict[str, str] = {}
        for key, value in values.items():
            column = table.column(key)
            if not column.editable:
                raise ValueError(f"{column.label} ({key}) is filled in by the app, not by hand")
            text = str(value or "").strip()
            if column.normalized:
                text = normalize_company_name(text)
            if not text:
                raise ValueError(f"{column.label} cannot be empty")
            prepared[key] = text
        return prepared

    @staticmethod
    def _refuse_duplicates(
        connection: sqlite3.Connection,
        table: TableDefinition,
        prepared: dict[str, str],
        excluding: str = "",
    ) -> None:
        for column in table.columns:
            if not column.unique or column.key not in prepared:
                continue
            clash = connection.execute(
                f"SELECT {table.id_column} FROM {table.key} "
                f"WHERE {column.key} = ? AND {table.id_column} <> ?",
                (prepared[column.key], excluding),
            ).fetchone()
            if clash is not None:
                raise DuplicateRow(
                    f"{prepared[column.key]!r} is already registered as {clash[table.id_column]}"
                    if column.key != table.id_column
                    else f"{prepared[column.key]!r} is already the identifier of another row"
                )

    @staticmethod
    def _claim_identifier(connection: sqlite3.Connection, table: TableDefinition) -> str:
        row = connection.execute(
            "SELECT next FROM master_data_counters WHERE table_key = ?", (table.key,)
        ).fetchone()
        number = int(row["next"]) if row else 1
        connection.execute(
            "INSERT INTO master_data_counters (table_key, next) VALUES (?, ?) "
            "ON CONFLICT(table_key) DO UPDATE SET next = excluded.next",
            (table.key, number + 1),
        )
        return f"{table.id_prefix}{number:04d}"
