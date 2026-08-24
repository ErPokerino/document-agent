"""Datasets as a single file, so one can be handed to someone else.

A dataset is a folder of PDFs beside their ground truth, which is fine on disk
and awkward to share: a directory does not travel through chat or email, and a
half-copied one is indistinguishable from a complete one. A zip does travel,
and it either opens or it does not.

The layout inside mirrors the store exactly — `documents/<name>.pdf` beside
`documents/<name>.json` — because the store already invites external producers
to write that shape. Unzipping an export into `backend/data/datasets/<name>`
by hand therefore works too, which is a property worth keeping.

`dataset.json` at the root says what the archive holds. It is written on
export and read on import when it is there, and nothing depends on it: an
archive assembled by hand with nothing but a `documents/` folder still opens.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from app.evaluation.datasets import DatasetStore, DatasetSummary, InvalidName


DOCUMENTS = "documents"
MANIFEST = "dataset.json"


class ArchiveError(ValueError):
    """Raised when an archive cannot be written, or cannot be trusted."""


def write_archive(store: DatasetStore, dataset: str) -> bytes:
    documents = _documents_of(store, dataset)
    if documents is None:
        raise ArchiveError(f"There is no dataset called {dataset!r} to export.")

    entities: set[str] = set()
    buffer = io.BytesIO()
    # No compression: a PDF is already compressed, and deflating it again buys
    # almost nothing for the time it costs on a large dataset.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        labelled = 0
        for document in documents:
            archive.writestr(
                f"{DOCUMENTS}/{document.name}",
                store.read_document(dataset, document.name),
            )
            label_file = store.read_labels(dataset, document.name)
            if label_file is None:
                continue
            labelled += 1
            entities.update(label_file.labels.keys())
            archive.writestr(
                f"{DOCUMENTS}/{PurePosixPath(document.name).stem}.json",
                json.dumps(
                    {"source": label_file.source, "labels": label_file.labels},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        archive.writestr(
            MANIFEST,
            json.dumps(
                {
                    "name": dataset,
                    "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "document_count": len(documents),
                    "labelled_count": labelled,
                    # Which fields the ground truth actually covers. An import
                    # into an app configured for other entities still works;
                    # this is what lets the reader see the mismatch.
                    "entities": sorted(entities),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return buffer.getvalue()


def read_archive(store: DatasetStore, data: bytes, name: str | None = None) -> DatasetSummary:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("That file is not a zip archive.") from exc

    with archive:
        manifest = _manifest(archive)
        dataset = (name or manifest.get("name") or "").strip()
        if not dataset:
            raise ArchiveError(
                "The archive does not say which dataset it is, so a name has to be given."
            )
        if _documents_of(store, dataset) is not None:
            raise ArchiveError(
                f"A dataset called {dataset!r} already exists. "
                f"Rename it, or import this one under another name."
            )

        pdfs, labels = _entries(archive)
        if not pdfs:
            raise ArchiveError(
                f"The archive holds no PDF documents under {DOCUMENTS}/, so there is "
                f"nothing to import."
            )

        store.create(dataset)
        for filename, entry in sorted(pdfs.items()):
            store.add_document(
                dataset,
                filename,
                archive.read(entry),
                labels=labels.get(PurePosixPath(filename).stem),
                # The store already has a word for ground truth that was made
                # somewhere else.
                source="imported",
            )

    return next(
        summary for summary in store.list_datasets() if summary.name == dataset
    )


# -- reading the archive safely ----------------------------------------------


def _documents_of(store: DatasetStore, dataset: str):
    """The dataset's documents, or None when there is no such dataset."""
    try:
        if not any(summary.name == dataset for summary in store.list_datasets()):
            return None
        return store.list_documents(dataset)
    except (InvalidName, FileNotFoundError):
        return None


def _manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    if MANIFEST not in archive.namelist():
        return {}
    try:
        manifest = json.loads(archive.read(MANIFEST))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def _safe_member(entry: str) -> str | None:
    """The plain filename inside `documents/`, or None if it is anything else.

    An archive is data from elsewhere, and a zip entry can name any path it
    likes — `../`, an absolute path, a drive letter. Only a single name
    directly inside `documents/` is read; everything else is skipped, which
    also quietly drops the README someone put beside it.
    """
    path = PurePosixPath(entry.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or entry.endswith("/"):
        return None
    if len(path.parts) != 2 or path.parts[0] != DOCUMENTS:
        return None
    return path.parts[1]


def _entries(archive: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    pdfs: dict[str, str] = {}
    labels: dict[str, dict[str, Any]] = {}
    for entry in archive.namelist():
        filename = _safe_member(entry)
        if filename is None:
            continue
        lowered = filename.lower()
        if lowered.endswith(".pdf"):
            pdfs[filename] = entry
        elif lowered.endswith(".json"):
            parsed = _labels_in(archive, entry)
            if parsed is not None:
                labels[PurePosixPath(filename).stem] = parsed
    return pdfs, labels


def _labels_in(archive: zipfile.ZipFile, entry: str) -> dict[str, Any] | None:
    """The labels in one file, or None if it does not hold any.

    The store accepts both `{"labels": {...}}` and a bare object of labels, so
    both are read here. Anything else is skipped rather than failing the whole
    import: one unreadable label file should not cost the other ninety-nine.
    """
    try:
        payload = json.loads(archive.read(entry))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    labels = payload.get("labels", payload)
    return labels if isinstance(labels, dict) else None
