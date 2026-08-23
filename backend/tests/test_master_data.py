"""Reference tables: one shape, many tables, and the rules that keep them usable."""

import pytest

from app.services.master_data import (
    TABLES,
    DuplicateRow,
    MasterDataStore,
    UnknownRow,
    UnknownTable,
)


@pytest.fixture
def store(tmp_path) -> MasterDataStore:
    return MasterDataStore(tmp_path / "docuflow.db")


def test_the_tables_on_offer_describe_their_own_columns() -> None:
    suppliers = TABLES["suppliers"]

    assert suppliers.label == "Suppliers"
    assert suppliers.id_column == "id_subject"
    assert [column.key for column in suppliers.columns] == [
        "id_subject",
        "name",
        "source",
        "created_at",
    ]
    assert suppliers.column("id_subject").editable is False
    assert suppliers.column("name").editable is True


def test_a_table_nobody_defined_is_refused(store) -> None:
    with pytest.raises(UnknownTable, match="invoices"):
        store.rows("invoices")


def test_a_new_table_is_empty(store) -> None:
    assert store.rows("suppliers") == []


def test_a_row_gets_an_identifier_and_its_name_normalized(store) -> None:
    row = store.add("suppliers", {"name": "ACME S.r.l."})

    assert row["id_subject"] == "S0001"
    # Only the normalized spelling is kept: the name on an invoice varies
    # between invoices from the same supplier, so it identifies nothing.
    assert row["name"] == "acme"


def test_identifiers_run_in_order_and_are_never_reused(store) -> None:
    store.add("suppliers", {"name": "First"})
    second = store.add("suppliers", {"name": "Second"})
    store.delete("suppliers", second["id_subject"])

    assert store.add("suppliers", {"name": "Third"})["id_subject"] == "S0003"


def test_the_same_supplier_cannot_be_registered_twice(store) -> None:
    store.add("suppliers", {"name": "ACME S.r.l."})

    with pytest.raises(DuplicateRow, match="S0001"):
        store.add("suppliers", {"name": "acme srl"})


def test_a_row_can_be_corrected(store) -> None:
    row = store.add("suppliers", {"name": "ACME"})

    updated = store.update("suppliers", row["id_subject"], {"name": "ACME International"})

    assert updated["name"] == "acme international"


def test_a_generated_column_cannot_be_written(store) -> None:
    row = store.add("suppliers", {"name": "ACME"})

    with pytest.raises(ValueError, match="id_subject"):
        store.update("suppliers", row["id_subject"], {"id_subject": "S9999"})


def test_acting_on_a_row_that_is_not_there_says_so(store) -> None:
    with pytest.raises(UnknownRow):
        store.update("suppliers", "S9999", {"name": "x"})
    with pytest.raises(UnknownRow):
        store.delete("suppliers", "S9999")


def test_rows_can_be_sorted_by_any_column_in_either_direction(store) -> None:
    for name in ("Zeta", "Acme", "Mid"):
        store.add("suppliers", {"name": name})

    ascending = [row["name"] for row in store.rows("suppliers", sort="name")]
    descending = [row["name"] for row in store.rows("suppliers", sort="name", descending=True)]
    by_id = [row["id_subject"] for row in store.rows("suppliers", sort="id_subject")]

    assert ascending == ["acme", "mid", "zeta"]
    assert descending == ["zeta", "mid", "acme"]
    assert by_id == ["S0001", "S0002", "S0003"]


def test_sorting_by_a_column_that_does_not_exist_is_refused(store) -> None:
    with pytest.raises(ValueError, match="turnover"):
        store.rows("suppliers", sort="turnover")


def test_rows_can_be_filtered_by_any_text_they_hold(store) -> None:
    store.add("suppliers", {"name": "ACME S.r.l."})
    store.add("suppliers", {"name": "Zeta Trasporti"})

    assert [row["name"] for row in store.rows("suppliers", query="trasp")] == ["zeta trasporti"]
    assert [row["id_subject"] for row in store.rows("suppliers", query="S0001")] == ["S0001"]


def test_seeding_adds_what_is_missing_and_leaves_the_rest(store) -> None:
    store.add("suppliers", {"name": "ACME S.r.l."})

    added = store.seed("suppliers", ["acme srl", "Zeta Trasporti", "Zeta Trasporti"])

    assert [row["name"] for row in added] == ["zeta trasporti"]
    assert len(store.rows("suppliers")) == 2


def test_a_row_can_be_read_back_by_identifier(store) -> None:
    row = store.add("suppliers", {"name": "ACME"})

    assert store.read("suppliers", row["id_subject"])["name"] == "acme"


def test_a_name_that_normalizes_to_nothing_is_refused(store) -> None:
    with pytest.raises(ValueError):
        store.add("suppliers", {"name": "   "})
