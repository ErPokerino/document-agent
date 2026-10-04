"""The stores' SQLite dialect, translated for PostgreSQL in one place."""

from app.services.db import Row, translate


def test_placeholders_become_psycopg_ones_outside_quotes_only() -> None:
    assert translate("SELECT * FROM t WHERE a = ? AND b = '?'") == "SELECT * FROM t WHERE a = %s AND b = '?'"


def test_percent_signs_survive_psycopg_interpolation() -> None:
    assert translate("SELECT ? = '%%' OR x LIKE ?") == "SELECT %s = '%%%%' OR x LIKE %s"


def test_types_keep_sqlite_widths() -> None:
    sql = translate("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, n INTEGER NOT NULL, s REAL)")

    assert sql == "CREATE TABLE t (id BIGSERIAL PRIMARY KEY, n BIGINT NOT NULL, s DOUBLE PRECISION)"


def test_case_insensitive_ordering_uses_lower() -> None:
    assert translate("SELECT * FROM t ORDER BY name COLLATE NOCASE DESC") == "SELECT * FROM t ORDER BY lower(name) DESC"


def test_a_row_reads_by_position_by_name_and_as_a_mapping() -> None:
    row = Row(("id", "name"), (3, "Acme"))

    assert row[0] == 3 and row["name"] == "Acme"
    assert dict(zip(row.keys(), row)) == {"id": 3, "name": "Acme"}
    assert tuple(row) == (3, "Acme")
