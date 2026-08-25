"""Reference tables that can be handed to someone else.

A register of suppliers is the sort of thing that already exists in a
spreadsheet somewhere, and the sort of thing a second machine needs a copy
of. CSV is what both ends of that already speak.
"""

import pytest

from app.services.master_data import DuplicateRow, MasterDataStore
from app.services.master_data_csv import ImportReport, rows_to_csv, csv_to_rows


@pytest.fixture
def store(tmp_path) -> MasterDataStore:
    store = MasterDataStore(tmp_path / "master.db")
    store.add("suppliers", {"name": "Acme S.p.A."})
    store.add("suppliers", {"name": "Globex Srl"})
    return store


def lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


# -- writing ------------------------------------------------------------------


def test_the_export_carries_a_header_and_a_row_each(store) -> None:
    csv_text = rows_to_csv(store, "suppliers")
    assert len(lines(csv_text)) == 3
    header = lines(csv_text)[0].split(",")
    assert "id_subject" in header
    assert "name" in header


def test_the_identifier_is_exported_so_a_copy_stays_the_same_register(store) -> None:
    """Ids are what a pipeline writes into a document. They have to survive."""
    original = {row["id_subject"] for row in store.rows("suppliers")}
    csv_text = rows_to_csv(store, "suppliers")
    assert all(identifier in csv_text for identifier in original)


def test_an_empty_table_still_exports_its_header(tmp_path) -> None:
    empty = MasterDataStore(tmp_path / "empty.db")
    assert len(lines(rows_to_csv(empty, "suppliers"))) == 1


# -- reading ------------------------------------------------------------------


def test_a_round_trip_reproduces_the_register(store, tmp_path) -> None:
    csv_text = rows_to_csv(store, "suppliers")
    target = MasterDataStore(tmp_path / "copy.db")
    report = csv_to_rows(target, "suppliers", csv_text)

    assert report.added == 2
    assert report.skipped == 0
    names = sorted(row["name"] for row in target.rows("suppliers"))
    assert names == sorted(row["name"] for row in store.rows("suppliers"))
    # And the ids came across rather than being reissued.
    assert {row["id_subject"] for row in target.rows("suppliers")} == {
        row["id_subject"] for row in store.rows("suppliers")
    }


def test_a_row_already_there_is_skipped_and_the_rest_still_land(store) -> None:
    """Three hundred suppliers where two exist must add two hundred and ninety-eight."""
    csv_text = "name\nAcme S.p.A.\nInitech Ltd\n"
    report = csv_to_rows(store, "suppliers", csv_text)
    assert report.added == 1
    assert report.skipped == 1
    assert any("Acme" in reason for reason in report.reasons)


def test_a_row_with_no_identifier_is_given_one(store, tmp_path) -> None:
    target = MasterDataStore(tmp_path / "fresh.db")
    report = csv_to_rows(target, "suppliers", "name\nInitech Ltd\n")
    assert report.added == 1
    assert target.rows("suppliers")[0]["id_subject"]


def test_columns_may_arrive_in_any_order_and_under_their_labels(tmp_path) -> None:
    """A spreadsheet round trip renames nothing, but a hand-made file might."""
    target = MasterDataStore(tmp_path / "fresh.db")
    report = csv_to_rows(target, "suppliers", "Name,ID subject\nInitech Ltd,SUBJ-9\n")
    assert report.added == 1
    assert target.rows("suppliers")[0]["id_subject"] == "SUBJ-9"


def test_a_column_the_table_does_not_have_is_ignored(tmp_path) -> None:
    target = MasterDataStore(tmp_path / "fresh.db")
    report = csv_to_rows(target, "suppliers", "name,vat_number\nInitech Ltd,IT01\n")
    assert report.added == 1
    assert "vat_number" not in target.rows("suppliers")[0]


def test_a_blank_row_is_skipped_rather_than_stored_empty(tmp_path) -> None:
    target = MasterDataStore(tmp_path / "fresh.db")
    report = csv_to_rows(target, "suppliers", "name\n\n   \nInitech Ltd\n")
    assert report.added == 1
    assert report.skipped == 0


def test_a_file_with_no_usable_column_is_refused(tmp_path) -> None:
    target = MasterDataStore(tmp_path / "fresh.db")
    with pytest.raises(ValueError) as raised:
        csv_to_rows(target, "suppliers", "colour,size\nred,large\n")
    assert "name" in str(raised.value).lower()


def test_something_that_is_not_csv_is_refused(tmp_path) -> None:
    target = MasterDataStore(tmp_path / "fresh.db")
    with pytest.raises(ValueError):
        csv_to_rows(target, "suppliers", "")


def test_the_report_says_what_happened_row_by_row(store) -> None:
    report = csv_to_rows(store, "suppliers", "name\nAcme S.p.A.\nGlobex Srl\nInitech Ltd\n")
    assert isinstance(report, ImportReport)
    assert report.added == 1
    assert report.skipped == 2
    assert len(report.reasons) == 2
