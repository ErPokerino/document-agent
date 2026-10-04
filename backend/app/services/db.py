"""One way to open the application database, shared by every store.

Two engines behind one interface. Locally, and wherever nothing else is
configured, the database is a SQLite file beside the data. With
`DOCUFLOW_DATABASE_URL` set to a PostgreSQL address — Cloud SQL, RDS, Azure
Database or any other — every store writes there instead, so the API and a
worker running elsewhere see the same rows. The stores write SQLite's dialect;
the few places PostgreSQL differs are translated here, once, rather than in
each store.

SQLite: under the default rollback journal a writer locks every reader out, so
a Lab run recording a document result could fail a list request in the UI with
`database is locked`. Write-ahead logging lets readers carry on during a write;
the busy timeout covers the remaining writer-writer case. One connection per
operation: sqlite3 connections are not safe to share between threads, and these
operations are short.
"""

import re
import sqlite3
import threading
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Sequence

from app import config

# Longer than any write these stores make, which are single rows or one run.
BUSY_TIMEOUT_SECONDS = 10
# Connections held open to PostgreSQL per process. The API and a worker each
# keep their own; a small managed instance accepts a few dozen in all.
POOL_SIZE = 5


def prepare(path: Path) -> None:
    """Make the store's folder and, on SQLite, switch the file to write-ahead logging.

    The folder is needed with either engine: the stores keep files beside the
    database, such as the PDFs a run was given.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if config.database_url():
        return
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
    finally:
        connection.close()


@contextmanager
def connect(path: Path) -> Iterator[Any]:
    url = config.database_url()
    if url:
        with _postgres(url) as connection:
            yield connection
        return
    connection = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def add_missing_columns(connection: Any, table: str, columns: dict[str, str]) -> None:
    """Add each column the table lacks, for a database written by an older app.

    `columns` maps a name to its declaration. A column is only ever added,
    never altered, so an older row reads back with the declared default.
    """
    if isinstance(connection, PostgresConnection):
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            )
        }
    else:
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def execute_script(connection: Any, script: str) -> None:
    """Run several `;`-separated statements, as sqlite3's executescript does."""
    if isinstance(connection, PostgresConnection):
        for statement in script.split(";"):
            if statement.strip():
                connection.execute(statement)
    else:
        connection.executescript(script)


# -- PostgreSQL ----------------------------------------------------------------


def translate(sql: str) -> str:
    """SQLite's dialect as the stores write it, in PostgreSQL's.

    Covers what the stores use and nothing more: placeholders, the
    auto-incrementing key, column types whose width differs, and
    case-insensitive ordering. Text inside quotes is left alone.
    """
    out: list[str] = []
    for index, part in enumerate(re.split(r"('(?:[^']|'')*')", sql)):
        if index % 2 == 1:
            out.append(part.replace("%", "%%"))
            continue
        part = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "BIGSERIAL PRIMARY KEY", part, flags=re.I)
        # SQLite's INTEGER is 64-bit and its REAL a double; PostgreSQL's are not.
        part = re.sub(r"\bINTEGER\b", "BIGINT", part)
        part = re.sub(r"\bREAL\b", "DOUBLE PRECISION", part)
        part = re.sub(r"([\w.]+)\s+COLLATE\s+NOCASE", r"lower(\1)", part, flags=re.I)
        part = part.replace("%", "%%").replace("?", "%s")
        out.append(part)
    return "".join(out)


class Row(tuple):
    """A result row read by position or by column name, like sqlite3.Row."""

    _names: tuple[str, ...] = ()

    def __new__(cls, names: tuple[str, ...], values: Sequence[Any]) -> "Row":
        row = super().__new__(cls, values)
        row._names = names
        return row

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        if isinstance(key, str):
            try:
                return tuple.__getitem__(self, self._names.index(key))
            except ValueError:
                raise IndexError(f"No column named {key}") from None
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._names)


class PostgresCursor:
    def __init__(self, connection: "PostgresConnection", cursor: Any) -> None:
        self._connection = connection
        self._cursor = cursor

    def _rows(self, rows: list[tuple[Any, ...]]) -> list[Row]:
        names = tuple(column.name for column in self._cursor.description or ())
        return [Row(names, row) for row in rows]

    def fetchone(self) -> Row | None:
        if self._cursor.description is None:
            return None
        row = self._cursor.fetchone()
        return None if row is None else self._rows([row])[0]

    def fetchall(self) -> list[Row]:
        if self._cursor.description is None:
            return []
        return self._rows(self._cursor.fetchall())

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int:
        """The key the last insert on this connection was given."""
        return int(self._connection.raw.execute("SELECT lastval()").fetchone()[0])


class PostgresConnection:
    """The slice of sqlite3.Connection the stores use, over a psycopg connection."""

    def __init__(self, raw: Any) -> None:
        self.raw = raw

    def execute(self, sql: str, parameters: Sequence[Any] | dict[str, Any] = ()) -> PostgresCursor:
        cursor = self.raw.cursor()
        cursor.execute(translate(sql), tuple(parameters) if not isinstance(parameters, dict) else parameters)
        return PostgresCursor(self, cursor)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> PostgresCursor:
        cursor = self.raw.cursor()
        cursor.executemany(translate(sql), [tuple(row) for row in rows])
        return PostgresCursor(self, cursor)

    def executescript(self, script: str) -> None:
        execute_script(self, script)

    def commit(self) -> None:
        self.raw.commit()


_pools: dict[str, Any] = {}
_pools_lock = threading.Lock()


def _configure(raw: Any) -> None:
    """Make values read and written the way the SQLite stores expect them.

    Booleans are stored as 0 and 1 in integer columns, as SQLite stores them;
    sums and averages come back as numbers rather than Decimal.
    """
    import psycopg
    from psycopg.adapt import Dumper, Loader

    class BoolAsInteger(Dumper):
        oid = psycopg.adapters.types["int8"].oid

        def dump(self, obj: bool) -> bytes:
            return b"1" if obj else b"0"

    class NumericAsNumber(Loader):
        def load(self, data: Any) -> int | float:
            value = Decimal(bytes(data).decode())
            return int(value) if value == value.to_integral_value() else float(value)

    raw.adapters.register_dumper(bool, BoolAsInteger)
    raw.adapters.register_loader("numeric", NumericAsNumber)


def _pool(url: str) -> Any:
    with _pools_lock:
        pool = _pools.get(url)
        if pool is None:
            import psycopg
            from psycopg_pool import ConnectionPool

            # Client-side binding: values are quoted into the statement, as
            # SQLite does, so `? IS NULL` needs no declared type.
            pool = ConnectionPool(
                url,
                min_size=1,
                max_size=POOL_SIZE,
                kwargs={"cursor_factory": psycopg.ClientCursor},
                configure=_configure,
                open=True,
            )
            _pools[url] = pool
        return pool


@contextmanager
def _postgres(url: str) -> Iterator[PostgresConnection]:
    # The pool commits when the block ends cleanly and rolls back otherwise.
    with _pool(url).connection() as raw:
        yield PostgresConnection(raw)


def close_pools() -> None:
    with _pools_lock:
        for pool in _pools.values():
            pool.close()
        _pools.clear()
