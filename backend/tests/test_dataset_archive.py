"""Datasets that can be handed to someone else.

A dataset is a folder of PDFs beside their ground truth. Sharing one meant
copying a directory; a single archive is what actually travels through email,
chat and a drive. The layout inside mirrors the store, because the store's own
docstring invites external producers to drop files into that shape.
"""

import io
import json
import zipfile

import pytest

from app.evaluation.datasets import DatasetStore, InvalidName
from app.evaluation.dataset_archive import (
    ArchiveError,
    read_archive,
    write_archive,
)


def seeded(tmp_path) -> DatasetStore:
    store = DatasetStore(tmp_path / "datasets")
    store.create("Invoices")
    store.add_document("Invoices", "a.pdf", b"%PDF-1.4 a", {"date": "2026-01-05"})
    store.add_document("Invoices", "b.pdf", b"%PDF-1.4 b", {"date": None})
    store.add_document("Invoices", "c.pdf", b"%PDF-1.4 c")
    return store


# -- writing ------------------------------------------------------------------


def test_an_archive_holds_the_documents_and_their_ground_truth(tmp_path) -> None:
    store = seeded(tmp_path)
    with zipfile.ZipFile(io.BytesIO(write_archive(store, "Invoices"))) as archive:
        names = set(archive.namelist())
    assert "documents/a.pdf" in names
    assert "documents/a.json" in names
    assert "documents/c.pdf" in names
    # c.pdf was never labelled, so there is no ground truth to carry.
    assert "documents/c.json" not in names


def test_the_archive_says_what_it_is(tmp_path) -> None:
    """A manifest, so the other end knows the name and what was labelled."""
    store = seeded(tmp_path)
    with zipfile.ZipFile(io.BytesIO(write_archive(store, "Invoices"))) as archive:
        manifest = json.loads(archive.read("dataset.json"))
    assert manifest["name"] == "Invoices"
    assert manifest["document_count"] == 3
    assert manifest["labelled_count"] == 2
    assert manifest["entities"] == ["date"]
    assert manifest["exported_at"]


def test_a_dataset_that_does_not_exist_cannot_be_exported(tmp_path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    with pytest.raises(ArchiveError):
        write_archive(store, "Nothing")


# -- reading ------------------------------------------------------------------


def test_an_archive_round_trips(tmp_path) -> None:
    source = seeded(tmp_path / "one")
    data = write_archive(source, "Invoices")

    target = DatasetStore(tmp_path / "two" / "datasets")
    summary = read_archive(target, data)

    assert summary.name == "Invoices"
    assert summary.document_count == 3
    assert summary.labelled_count == 2
    assert target.read_document("Invoices", "a.pdf") == b"%PDF-1.4 a"
    labels = target.read_labels("Invoices", "a.pdf")
    assert labels.labels == {"date": "2026-01-05"}
    # A label that arrived from elsewhere is not a manual one, and the store
    # already has a word for that.
    assert labels.source == "imported"


def test_a_null_label_survives_because_it_means_something(tmp_path) -> None:
    """Absent-in-document is a labelled answer, not a missing label."""
    source = seeded(tmp_path / "one")
    target = DatasetStore(tmp_path / "two" / "datasets")
    read_archive(target, write_archive(source, "Invoices"))
    assert target.read_labels("Invoices", "b.pdf").labels == {"date": None}


def test_the_name_can_be_overridden_on_the_way_in(tmp_path) -> None:
    source = seeded(tmp_path / "one")
    target = DatasetStore(tmp_path / "two" / "datasets")
    summary = read_archive(target, write_archive(source, "Invoices"), name="Supplier sample")
    assert summary.name == "Supplier sample"


def test_importing_over_an_existing_dataset_is_refused(tmp_path) -> None:
    """Silently merging into someone's ground truth is not a recoverable mistake."""
    store = seeded(tmp_path)
    with pytest.raises(ArchiveError) as raised:
        read_archive(store, write_archive(store, "Invoices"))
    assert "Invoices" in str(raised.value)


# -- refusing what should not be read -----------------------------------------


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_an_entry_that_climbs_out_of_the_dataset_is_refused(tmp_path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    for escape in ("../evil.pdf", "documents/../../evil.pdf", "/etc/evil.pdf"):
        with pytest.raises((ArchiveError, InvalidName)):
            read_archive(store, make_zip({escape: b"%PDF"}), name="Zipped")


def test_files_that_are_not_documents_or_labels_are_ignored(tmp_path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    data = make_zip(
        {
            "dataset.json": json.dumps({"name": "Mixed"}).encode(),
            "documents/a.pdf": b"%PDF-1.4 a",
            "documents/a.json": json.dumps({"labels": {"date": "2026-01-01"}}).encode(),
            "documents/notes.txt": b"ignore me",
            "README.md": b"ignore me too",
        }
    )
    summary = read_archive(store, data)
    assert summary.document_count == 1
    assert [d.name for d in store.list_documents("Mixed")] == ["a.pdf"]


def test_something_that_is_not_a_zip_is_refused(tmp_path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    with pytest.raises(ArchiveError):
        read_archive(store, b"this is not a zip", name="Nope")


def test_an_archive_with_no_documents_is_refused(tmp_path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    with pytest.raises(ArchiveError):
        read_archive(store, make_zip({"README.md": b"nothing here"}), name="Empty")


def test_a_label_that_is_not_an_object_is_left_out_rather_than_crashing(tmp_path) -> None:
    store = DatasetStore(tmp_path / "datasets")
    data = make_zip({"documents/a.pdf": b"%PDF-1.4", "documents/a.json": b"[1, 2, 3]"})
    summary = read_archive(store, data, name="Odd")
    assert summary.document_count == 1
    assert summary.labelled_count == 0


# -- over the API -------------------------------------------------------------


def test_export_and_import_over_the_api(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app import main

    store = seeded(tmp_path)
    monkeypatch.setattr(main, "dataset_store", store)

    with TestClient(main.app) as client:
        exported = client.get("/api/datasets/Invoices/export.zip")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        assert "Invoices.zip" in exported.headers["content-disposition"]

        created = client.post(
            "/api/datasets/import",
            files={"file": ("Invoices.zip", exported.content, "application/zip")},
            data={"name": "Copy of invoices"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "Copy of invoices"
        assert created.json()["document_count"] == 3
        assert created.json()["labelled_count"] == 2


def test_importing_a_name_already_taken_is_refused_with_a_reason(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app import main

    store = seeded(tmp_path)
    monkeypatch.setattr(main, "dataset_store", store)

    with TestClient(main.app) as client:
        exported = client.get("/api/datasets/Invoices/export.zip").content
        clash = client.post(
            "/api/datasets/import",
            files={"file": ("Invoices.zip", exported, "application/zip")},
        )
    assert clash.status_code == 409
    assert "Invoices" in clash.json()["detail"]


def test_exporting_a_dataset_that_is_not_there_is_a_404(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(main, "dataset_store", DatasetStore(tmp_path / "datasets"))
    with TestClient(main.app) as client:
        assert client.get("/api/datasets/Missing/export.zip").status_code == 404


def test_a_file_that_is_not_an_archive_is_refused_over_the_api(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(main, "dataset_store", DatasetStore(tmp_path / "datasets"))
    with TestClient(main.app) as client:
        response = client.post(
            "/api/datasets/import",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            data={"name": "Nope"},
        )
    assert response.status_code == 409
    assert "zip" in response.json()["detail"].lower()
