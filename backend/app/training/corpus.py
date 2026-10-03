"""The text of labelled documents, read the way a pipeline will read them.

A model trained on text has to be served the same kind of text: a TF-IDF
vocabulary learned from Document AI OCR sees different tokens in a PDF's
embedded text, and the similarity it reports means something else. So the
corpus is read by the reading steps of a named pipeline — the ones before its
first step that produces fields — and those steps are recorded with the model.

Readings come from the stored Document AI readings where they exist. Training
measures nothing about time or cost, and an OCR page read once for a Lab run
should not be paid for again to learn from.
"""

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from app.evaluation.scoring import _normalize_date
from app.pipeline.compiler import PipelineError
from app.pipeline.definition import (
    Artifact,
    PipelineDefinition,
    PipelineStep,
    StepKind,
    contract_for,
    is_pdf_text_fallback,
)
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.steps import InspectPdf, ReadPdfText, ReadWithDocumentAi

READER_KINDS = (StepKind.read_pdf_text, StepKind.document_ai_ocr, StepKind.document_ai_layout)


@dataclass(frozen=True)
class LabelledDocument:
    dataset: str
    name: str
    sha256: str
    content: bytes
    labels: dict[str, Any]


@dataclass(frozen=True)
class ReadDocument:
    document: LabelledDocument
    text: str
    total_pages: int = 0
    processed_pages: int = 0


def reading_steps(definition: PipelineDefinition) -> list[PipelineStep]:
    """The steps that read the document before anything fills a field."""
    readers: list[PipelineStep] = []
    for step in definition.steps:
        if Artifact.entities in contract_for(step.kind).produces:
            break
        if step.kind in READER_KINDS:
            readers.append(step)
    if not readers:
        raise PipelineError(
            f"The pipeline '{definition.name}' reads no text before its first step that fills fields."
        )
    return readers


def reader_signature(steps: list[PipelineStep]) -> list[dict[str, Any]]:
    """What a model records about how its text was read, and what a pipeline is compared on."""
    return [
        {
            "kind": step.kind.value,
            "processor_id": step.config.get("processor_id") if step.kind is not StepKind.read_pdf_text else None,
            "only_without_pdf_text": is_pdf_text_fallback(step),
        }
        for step in steps
    ]


def same_reading(recorded: list[dict[str, Any]], current: list[dict[str, Any]]) -> bool:
    """Whether two readings are the same kind of text: the same readers, in order.

    A processor version is not compared: the same OCR processor at another
    version still produces OCR text, and refusing it would refuse every
    pipeline the moment Google ships a version.
    """
    def shape(signature: list[dict[str, Any]]) -> list[tuple[str, str, bool]]:
        return [
            (entry["kind"], str(entry.get("processor_id") or "").split("/processorVersions/")[0], bool(entry.get("only_without_pdf_text")))
            for entry in signature
        ]

    return shape(recorded) == shape(current)


def executable_readers(steps: list[PipelineStep], page_limit: int) -> list[Any]:
    executable: list[Any] = [InspectPdf(page_limit=page_limit)]
    for index, step in enumerate(steps):
        if step.kind is StepKind.read_pdf_text:
            executable.append(ReadPdfText(feeds_model=True, ocr_follows=any(is_pdf_text_fallback(later) for later in steps[index + 1 :])))
        else:
            executable.append(
                ReadWithDocumentAi(
                    step.kind.value,
                    str(step.config.get("processor_id") or ""),
                    feeds_model=True,
                    project_id=step.config.get("project_id"),
                    location=step.config.get("location"),
                    only_without_pdf_text=is_pdf_text_fallback(step),
                )
            )
    return executable


def before_cutoff(labels: dict[str, Any], entity: str, cutoff: date) -> bool:
    """Whether a document is dated before the cutoff, by its own label."""
    normalized = _normalize_date(labels.get(entity))
    return normalized is not None and date.fromisoformat(normalized) < cutoff


async def read_corpus(
    documents: list[LabelledDocument],
    steps: list[Any],
    make_context: Callable[[str, bytes], PipelineContext],
    on_progress: Callable[[int], None] | None = None,
    cancelled: asyncio.Event | None = None,
) -> tuple[list[ReadDocument], list[tuple[str, str]]]:
    """Each document's text, and the documents that could not be read, with why."""
    read: list[ReadDocument] = []
    skipped: list[tuple[str, str]] = []
    for position, document in enumerate(documents, start=1):
        if cancelled is not None and cancelled.is_set():
            raise asyncio.CancelledError()
        label = f"{document.dataset}/{document.name}"
        try:
            context = await DocumentPipeline(steps).run(make_context(document.name, document.content))
        except (ValueError, OSError) as exc:
            skipped.append((label, str(exc)))
        except Exception as exc:  # noqa: BLE001 - a provider failure skips one document, not the corpus
            skipped.append((label, str(exc)))
        else:
            text = str(context.artifacts.get("document_text") or "").strip()
            if text:
                read.append(
                    ReadDocument(
                        document,
                        text,
                        total_pages=int(context.artifacts.get("page_count") or 0),
                        processed_pages=int(context.artifacts.get("processed_pages") or 0),
                    )
                )
            else:
                skipped.append((label, "No text was read from it."))
        if on_progress is not None:
            on_progress(position)
    return read, skipped
