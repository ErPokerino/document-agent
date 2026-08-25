"""Reference tables as CSV, so a register can be moved or edited elsewhere.

A supplier register is the sort of thing that already exists in a spreadsheet,
and the sort of thing a second machine needs a copy of. CSV is what both ends
of that already speak, and unlike a dataset there are no binaries to carry — a
table is text.

Importing is deliberately forgiving about shape and strict about content. A
column the table does not have is ignored, headers may be keys or labels and
in any order, and a row that cannot be stored is skipped with a reason rather
than failing the file: three hundred suppliers where two already exist should
add two hundred and ninety-eight.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from app.services.master_data import DuplicateRow, MasterDataStore, TableDefinition


@dataclass
class ImportReport:
    added: int = 0
    skipped: int = 0
    # One line per skipped row, naming the row and why it did not go in.
    reasons: list[str] = field(default_factory=list)


def rows_to_csv(store: MasterDataStore, table_key: str) -> str:
    """Every row, under the column keys the importer reads back."""
    table = store.table(table_key)
    columns = [column.key for column in table.columns]

    buffer = io.StringIO()
    # Excel reads \r\n, and so does everything else.
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in store.rows(table_key):
        writer.writerow({key: row.get(key, "") for key in columns})
    return buffer.getvalue()


def csv_to_rows(store: MasterDataStore, table_key: str, text: str) -> ImportReport:
    """Add every row the file holds that the table can take."""
    table = store.table(table_key)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("That file has no header row, so its columns cannot be read.")

    mapping = _map_columns(table, reader.fieldnames)
    required = table.match_column or table.seed_column
    if required not in mapping.values():
        raise ValueError(
            f"The file has no {required!r} column. "
            f"{table.label} needs one to identify a row."
        )

    report = ImportReport()
    for position, raw in enumerate(reader, start=2):
        values = {
            column: (raw.get(header) or "").strip()
            for header, column in mapping.items()
            if (raw.get(header) or "").strip()
        }
        # A trailing newline or a spacer line is not a row anyone meant to add.
        if not values.get(required):
            continue

        label = values[required]
        try:
            store.add(table_key, values, source="imported")
        except DuplicateRow:
            report.skipped += 1
            report.reasons.append(f"Row {position}: {label} is already in the table.")
        except ValueError as exc:
            report.skipped += 1
            report.reasons.append(f"Row {position}: {label} could not be added. {exc}")
        else:
            report.added += 1

    return report


def _map_columns(table: TableDefinition, headers: list[str]) -> dict[str, str]:
    """Header text to column key, by key or by label, case and spacing aside.

    A file that came out of the exporter uses the keys. One made by hand, or
    saved out of a spreadsheet someone renamed, may well use the labels.
    """
    by_name: dict[str, str] = {}
    # Only what a person may set. `source` and `created_at` are exported because
    # they say where a row came from, and refused on the way back in because
    # the store fills them: an imported row was imported, whatever the file it
    # came from used to say.
    for column in table.editable_columns:
        by_name[_simplify(column.key)] = column.key
        by_name[_simplify(column.label)] = column.key

    mapping: dict[str, str] = {}
    for header in headers:
        if header is None:
            continue
        column = by_name.get(_simplify(header))
        if column is not None:
            mapping[header] = column
    return mapping


def _simplify(text: str) -> str:
    return "".join(character for character in text.lower() if character.isalnum())
