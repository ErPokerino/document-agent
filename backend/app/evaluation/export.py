"""Flatten an evaluation into CSV, one row per extracted entity.

The long shape is deliberate: it drops straight into a spreadsheet pivot or a
dataframe, and every row carries the run context, so exports from several runs
can be concatenated and compared without losing which run a row came from.
"""

import csv
import io
from typing import Any

from app.evaluation.store import EvaluationDetail


COLUMNS = (
    "run_id",
    "dataset",
    "model",
    "provider",
    "pipeline",
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
    "entity",
    "expected",
    "actual",
    "confidence",
    "matched",
    "error",
)


def _cell(value: Any) -> str:
    """None becomes an empty cell; numbers keep their own formatting."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
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
        "provider": detail.provider,
        "pipeline": detail.pipeline,
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
    }

    for document in detail.documents:
        base = {
            **context,
            "document": document.name,
            "document_status": document.status,
            "elapsed_ms": document.elapsed_ms,
            "prompt_tokens": document.prompt_tokens,
            "completion_tokens": document.completion_tokens,
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
                "matched": item.matched,
            }
            writer.writerow({column: _cell(row.get(column)) for column in COLUMNS})

    return buffer.getvalue()
