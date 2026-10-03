"""Flatten an evaluation into CSV, one row per extracted entity.

The long shape is deliberate: it drops straight into a spreadsheet pivot or a
dataframe, and every row carries the run context, so exports from several runs
can be concatenated and compared without losing which run a row came from.
"""

import csv
import io
import json
from typing import Any

from app.evaluation.store import EvaluationDetail
from app.services.spreadsheet import safe_text


COLUMNS = (
    "run_id",
    "dataset",
    "model",
    "extractor_name",
    "extractor_processor",
    "extractor_version",
    "extractor_base_model",
    "additional_extractors",
    "provider",
    "pipeline",
    "fingerprint",
    "steps",
    "execution_profile",
    "parameters",
    "quantization",
    "model_size_bytes",
    "context_length",
    "parallel",
    "seed",
    "thinking_level",
    "max_pages",
    "created_at",
    "document",
    "document_status",
    "elapsed_ms",
    "prompt_tokens",
    "completion_tokens",
    "ocr_pages",
    "layout_pages",
    "custom_extractor_pages",
    # Pages read back from stored readings: not sent, not billed, not timed.
    "cached_pages",
    "usage_complete",
    "entity",
    "expected",
    "actual",
    "confidence",
    # A step's own number for its answer, such as a similarity; empty otherwise.
    "score",
    "matched",
    "error",
)


def _cell(value: Any) -> str:
    """None becomes an empty cell; numbers keep their own formatting."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return safe_text(value)
    return str(value)


def evaluation_to_csv(detail: EvaluationDetail) -> str:
    buffer = io.StringIO()
    # Excel reads a bare \n fine, and \r\n would double up on Windows readers.
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()

    context = {
        "run_id": detail.id,
        "dataset": detail.dataset,
        "model": detail.model,
        "extractor_name": (detail.extraction_engine or {}).get("display_name"),
        "extractor_processor": (detail.extraction_engine or {}).get("processor_id"),
        "extractor_version": (detail.extraction_engine or {}).get("version"),
        "extractor_base_model": (detail.extraction_engine or {}).get("base_model"),
        "additional_extractors": json.dumps(detail.extraction_engine["additional_processors"]) if (detail.extraction_engine or {}).get("additional_processors") else None,
        "provider": detail.provider,
        "pipeline": detail.pipeline,
        "fingerprint": detail.fingerprint,
        "steps": " > ".join(detail.steps),
        "execution_profile": (
            detail.execution_profile.profile if detail.execution_profile is not None else None
        ),
        "parameters": (
            detail.execution_profile.parameters if detail.execution_profile is not None else None
        ),
        "quantization": (
            detail.execution_profile.quantization if detail.execution_profile is not None else None
        ),
        "model_size_bytes": (
            detail.execution_profile.model_size_bytes
            if detail.execution_profile is not None
            else None
        ),
        "context_length": (
            detail.execution_profile.context_length
            if detail.execution_profile is not None
            else None
        ),
        "parallel": (
            detail.execution_profile.parallel if detail.execution_profile is not None else None
        ),
        "seed": detail.execution_profile.seed if detail.execution_profile is not None else None,
        "thinking_level": (
            detail.execution_profile.thinking_level
            if detail.execution_profile is not None
            else None
        ),
        "max_pages": detail.max_pages,
        "created_at": detail.created_at,
        "usage_complete": detail.usage_complete,
    }

    for document in detail.documents:
        base = {
            **context,
            "document": document.name,
            "document_status": document.status,
            "elapsed_ms": document.elapsed_ms,
            "prompt_tokens": document.prompt_tokens,
            "completion_tokens": document.completion_tokens,
            "ocr_pages": document.ocr_pages,
            "layout_pages": document.layout_pages,
            "custom_extractor_pages": document.custom_extractor_pages,
            "cached_pages": document.cached_pages,
            "error": document.error,
        }
        if not document.items:
            # A document that never produced a field still belongs in the export;
            # dropping it would hide exactly the failures worth looking at.
            writer.writerow({column: _cell(base.get(column)) for column in COLUMNS})
            continue
        for item in document.items:
            row = {
                **base,
                "entity": item.entity,
                "expected": item.expected,
                "actual": item.actual,
                "confidence": item.confidence,
                "score": item.score,
                "matched": item.matched,
            }
            writer.writerow({column: _cell(row.get(column)) for column in COLUMNS})

    return buffer.getvalue()
