"""Filesystem-backed store for evaluation datasets.

The layout is deliberately plain, because three different producers write into
it: the app when a reviewed run is promoted to ground truth, the app when a user
labels an ad-hoc document, and any external process that simply drops files in.

    <root>/<dataset>/documents/invoice21.pdf
    <root>/<dataset>/documents/invoice21.json

The label file is `{"source": ..., "labels": {...}}`, but a bare object of
labels is accepted too, since that is the least a producer can be asked to
write. A key present with a null value means "the model must return nothing
here"; a key that is absent means "not labelled", and is left out of scoring.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Anything outside this cannot traverse out of the dataset root.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,127}$")
LABEL_SOURCES = ("manual", "promoted_run", "imported")


class InvalidName(ValueError):
    """Raised for a dataset or document name that is not safe to use as a path."""


@dataclass(frozen=True)
class DatasetSummary:
    name: str
    document_count: int
    labelled_count: int


@dataclass(frozen=True)
class DocumentSummary:
    name: str
    size_bytes: int
    labelled: bool
    labelled_entities: list[str]
    label_source: str | None = None
    label_error: str | None = None


@dataclass(frozen=True)
class LabelFile:
    source: str
    labels: dict[str, Any]
    updated_at: str | None = None


def _validate(name: str, kind: str) -> str:
    if not isinstance(name, str) or not SAFE_NAME.match(name) or name.strip() != name:
        raise InvalidName(f"{kind} name must be plain text without path separators: {name!r}")
    return name


class DatasetStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- paths ---------------------------------------------------------------

    def _dataset_dir(self, dataset: str) -> Path:
        return self.root / _validate(dataset, "Dataset")

    def _documents_dir(self, dataset: str) -> Path:
        return self._dataset_dir(dataset) / "documents"

    def _document_path(self, dataset: str, document: str) -> Path:
        return self._documents_dir(dataset) / _validate(document, "Document")

    def _label_path(self, dataset: str, document: str) -> Path:
        return self._document_path(dataset, document).with_suffix(".json")

    # -- datasets ------------------------------------------------------------

    def list_datasets(self) -> list[DatasetSummary]:
        if not self.root.exists():
            return []
        summaries: list[DatasetSummary] = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or not SAFE_NAME.match(entry.name):
                continue
            documents = self.list_documents(entry.name)
            summaries.append(
                DatasetSummary(
                    name=entry.name,
                    document_count=len(documents),
                    labelled_count=sum(document.labelled for document in documents),
                )
            )
        return summaries

    def create(self, name: str) -> DatasetSummary:
        directory = self._dataset_dir(name)
        if directory.exists():
            raise ValueError(f"A dataset named {name!r} already exists")
        (directory / "documents").mkdir(parents=True)
        return DatasetSummary(name=name, document_count=0, labelled_count=0)

    def delete(self, name: str) -> None:
        import shutil

        directory = self._dataset_dir(name)
        if directory.exists():
            shutil.rmtree(directory)

    # -- documents -----------------------------------------------------------

    def list_documents(self, dataset: str) -> list[DocumentSummary]:
        directory = self._documents_dir(dataset)
        if not directory.exists():
            return []
        summaries: list[DocumentSummary] = []
        for entry in sorted(directory.glob("*.pdf")):
            error: str | None = None
            label_file: LabelFile | None = None
            try:
                label_file = self.read_labels(dataset, entry.name)
            except ValueError as exc:
                error = str(exc)
            summaries.append(
                DocumentSummary(
                    name=entry.name,
                    size_bytes=entry.stat().st_size,
                    labelled=label_file is not None,
                    labelled_entities=sorted(label_file.labels) if label_file else [],
                    label_source=label_file.source if label_file else None,
                    label_error=error,
                )
            )
        return summaries

    def add_document(
        self,
        dataset: str,
        filename: str,
        content: bytes,
        labels: dict[str, Any] | None = None,
        source: str = "manual",
    ) -> DocumentSummary:
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Only PDF documents can be added to a dataset")
        path = self._document_path(dataset, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if labels is not None:
            self.set_labels(dataset, filename, labels, source=source)
        return next(
            document for document in self.list_documents(dataset) if document.name == filename
        )

    def remove_document(self, dataset: str, document: str) -> None:
        self._document_path(dataset, document).unlink(missing_ok=True)
        self._label_path(dataset, document).unlink(missing_ok=True)

    def read_document(self, dataset: str, document: str) -> bytes:
        return self._document_path(dataset, document).read_bytes()

    # -- labels --------------------------------------------------------------

    def read_labels(self, dataset: str, document: str) -> LabelFile | None:
        path = self._label_path(dataset, document)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name} must contain a JSON object")

        raw_labels = payload.get("labels", payload)
        if not isinstance(raw_labels, dict):
            raise ValueError(f"{path.name}: 'labels' must be a JSON object")
        # A bare object of labels has no envelope keys to strip.
        labels = {
            key: value
            for key, value in raw_labels.items()
            if raw_labels is not payload or key not in {"source", "updated_at"}
        }
        return LabelFile(
            source=str(payload.get("source", "imported")),
            labels=labels,
            updated_at=payload.get("updated_at"),
        )

    def set_labels(
        self,
        dataset: str,
        document: str,
        labels: dict[str, Any],
        source: str = "manual",
    ) -> LabelFile:
        if source not in LABEL_SOURCES:
            raise ValueError(f"Unknown label source {source!r}")
        label_file = LabelFile(
            source=source,
            labels=labels,
            updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        path = self._label_path(dataset, document)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "source": label_file.source,
                        "updated_at": label_file.updated_at,
                        "labels": label_file.labels,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return label_file
