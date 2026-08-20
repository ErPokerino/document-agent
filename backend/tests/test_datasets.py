import json

import pytest

from app.evaluation.datasets import DatasetStore, InvalidName


def pdf_bytes() -> bytes:
    import pymupdf

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Invoice")
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def store(tmp_path) -> DatasetStore:
    return DatasetStore(tmp_path / "datasets")


def test_a_new_store_has_no_datasets(store) -> None:
    assert store.list_datasets() == []


def test_a_created_dataset_is_listed(store) -> None:
    store.create("invoices-2026")

    assert [dataset.name for dataset in store.list_datasets()] == ["invoices-2026"]


def test_creating_the_same_dataset_twice_is_rejected(store) -> None:
    store.create("invoices")

    with pytest.raises(ValueError, match="already exists"):
        store.create("invoices")


def test_a_document_added_through_the_api_is_listed_without_labels(store) -> None:
    store.create("invoices")
    store.add_document("invoices", "invoice21.pdf", pdf_bytes())

    documents = store.list_documents("invoices")
    assert [document.name for document in documents] == ["invoice21.pdf"]
    assert documents[0].labelled is False
    assert documents[0].labelled_entities == []


def test_labels_written_by_the_api_round_trip(store) -> None:
    store.create("invoices")
    store.add_document("invoices", "invoice21.pdf", pdf_bytes())

    store.set_labels("invoices", "invoice21.pdf", {"date": "2026-07-31", "total_amount": 125.31}, source="manual")

    assert store.read_labels("invoices", "invoice21.pdf").labels == {
        "date": "2026-07-31",
        "total_amount": 125.31,
    }
    assert store.list_documents("invoices")[0].labelled is True


def test_an_explicit_null_label_is_preserved(store) -> None:
    store.create("invoices")
    store.add_document("invoices", "invoice21.pdf", pdf_bytes())

    store.set_labels("invoices", "invoice21.pdf", {"supplier_name": None}, source="manual")

    # "the model must return nothing here", not "not labelled".
    labels = store.read_labels("invoices", "invoice21.pdf").labels
    assert "supplier_name" in labels
    assert labels["supplier_name"] is None


def test_files_dropped_straight_into_the_folder_are_discovered(store, tmp_path) -> None:
    # An external process populates the dataset without going through the API.
    folder = tmp_path / "datasets" / "dropped" / "documents"
    folder.mkdir(parents=True)
    (folder / "invoice99.pdf").write_bytes(pdf_bytes())
    (folder / "invoice99.json").write_text(
        json.dumps({"labels": {"currency": "EUR"}}), encoding="utf-8"
    )

    documents = store.list_documents("dropped")

    assert [document.name for document in documents] == ["invoice99.pdf"]
    assert documents[0].labelled is True
    assert store.read_labels("dropped", "invoice99.pdf").labels == {"currency": "EUR"}


def test_a_bare_json_object_is_accepted_as_the_labels(store, tmp_path) -> None:
    # The simplest thing an automated producer can write.
    folder = tmp_path / "datasets" / "dropped" / "documents"
    folder.mkdir(parents=True)
    (folder / "invoice99.pdf").write_bytes(pdf_bytes())
    (folder / "invoice99.json").write_text(json.dumps({"currency": "EUR"}), encoding="utf-8")

    assert store.read_labels("dropped", "invoice99.pdf").labels == {"currency": "EUR"}


def test_a_pdf_without_labels_is_still_listed(store, tmp_path) -> None:
    folder = tmp_path / "datasets" / "dropped" / "documents"
    folder.mkdir(parents=True)
    (folder / "unlabelled.pdf").write_bytes(pdf_bytes())

    documents = store.list_documents("dropped")

    assert documents[0].labelled is False
    assert store.read_labels("dropped", "unlabelled.pdf") is None


def test_a_corrupt_label_file_does_not_hide_the_document(store, tmp_path) -> None:
    folder = tmp_path / "datasets" / "dropped" / "documents"
    folder.mkdir(parents=True)
    (folder / "invoice99.pdf").write_bytes(pdf_bytes())
    (folder / "invoice99.json").write_text("{ broken", encoding="utf-8")

    documents = store.list_documents("dropped")

    assert documents[0].labelled is False
    assert documents[0].label_error is not None


def test_the_pdf_content_can_be_read_back(store) -> None:
    store.create("invoices")
    content = pdf_bytes()
    store.add_document("invoices", "invoice21.pdf", content)

    assert store.read_document("invoices", "invoice21.pdf") == content


def test_a_document_can_be_removed(store) -> None:
    store.create("invoices")
    store.add_document("invoices", "invoice21.pdf", pdf_bytes())

    store.remove_document("invoices", "invoice21.pdf")

    assert store.list_documents("invoices") == []


@pytest.mark.parametrize(
    "name",
    ["..", "../escape", "nested/name", "nested\\name", "C:/absolute", "", ".", "  "],
)
def test_names_that_could_escape_the_dataset_folder_are_rejected(store, name) -> None:
    with pytest.raises(InvalidName):
        store.create(name)


def test_document_names_are_validated_too(store) -> None:
    store.create("invoices")

    with pytest.raises(InvalidName):
        store.add_document("invoices", "../../evil.pdf", pdf_bytes())


def test_only_pdf_documents_are_accepted(store) -> None:
    store.create("invoices")

    with pytest.raises(ValueError, match="PDF"):
        store.add_document("invoices", "notes.txt", b"hello")
