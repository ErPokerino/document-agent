"""Run a whole dataset through the extraction pipeline and score the results.

One document is one full model call, so a dataset of twenty invoices is minutes
of work. This runs as a background task that reports progress into the store,
and a failure on one document is recorded and stepped over rather than losing
the whole run.
"""

import asyncio
import time
from typing import Any, Callable, Iterable

from app.domain.models import EntityDefinition, PromptConfiguration
from app.evaluation.datasets import DatasetStore
from app.evaluation.scoring import score_document
from app.evaluation.store import EvaluationStore
from app.pipeline.definition import DEFAULT_PIPELINE_NAME
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.services.document_ai import DocumentAiError
from app.services.gemini import GeminiError
from app.services.lm_studio import LMStudioError
from app.services.run_store import RunStore


# Anything here means the inference runtime is no longer serving: it was
# unloaded, it crashed, or the process is gone. Every document after one of
# these fails in milliseconds against nothing, so the run stops instead of
# filling the table with nine identical errors.
_RUNTIME_GONE = (
    "model is unloaded",
    "unloaded, replaced, or stopped",
    "engine protocol predict request failed",
    "fetch failed",
    "is not reachable",
    "failed to encode the page image",
)


def model_is_gone(message: str) -> bool:
    """Whether this failure means there is nothing left to ask."""
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _RUNTIME_GONE)


async def run_evaluation(
    *,
    evaluation_id: int,
    evaluations: EvaluationStore,
    datasets: DatasetStore,
    run_store: RunStore | None,
    dataset: str,
    documents: Iterable[tuple[str, dict[str, Any]]],
    entities: list[EntityDefinition],
    prompts: PromptConfiguration,
    model: str,
    max_pages: int,
    steps: list[Any],
    # One place builds a pipeline context, and it is not here. Assembling a
    # second one is how the Lab ended up running without the Google Cloud
    # settings that Workspace had.
    make_context: Callable[[str, bytes], PipelineContext],
    pipeline_name: str = DEFAULT_PIPELINE_NAME,
    pipeline_steps: list[str] | None = None,
    provider: str = "lm_studio",
    cancelled: asyncio.Event | None = None,
) -> None:
    try:
        for name, labels in documents:
            if cancelled is not None and cancelled.is_set():
                evaluations.finish(evaluation_id, "cancelled")
                return

            started = time.perf_counter()
            try:
                content = datasets.read_document(dataset, name)
                # The steps hold no per-document state, so one compiled
                # pipeline serves the whole run.
                result = await DocumentPipeline(steps).run(make_context(name, content))
                if cancelled is not None and cancelled.is_set():
                    evaluations.finish(evaluation_id, "cancelled")
                    return
            except asyncio.CancelledError:
                evaluations.finish(evaluation_id, "cancelled")
                raise
            except (OSError, ValueError, LMStudioError, GeminiError, DocumentAiError) as exc:
                evaluations.record_document_failure(evaluation_id, name, str(exc))
                if model_is_gone(str(exc)):
                    scored = evaluations.attempted_documents(evaluation_id)
                    evaluations.finish(
                        evaluation_id,
                        "partial" if any(s == "ok" for s in scored.values()) else "failed",
                        error=(
                            f"The run stopped at {name}, with "
                            f"{len([s for s in scored.values() if s == 'ok'])} of "
                            f"{evaluations.get_evaluation(evaluation_id).total_documents} "
                            f"documents scored. {exc} The model stopped serving at that point, "
                            f"so the remaining documents were left unprocessed rather than "
                            f"recorded as wrong."
                        ),
                    )
                    return
                continue

            elapsed_ms = round((time.perf_counter() - started) * 1000)
            extraction = result.artifacts["extraction"]
            try:
                outcomes = score_document(entities, labels, extraction)
            except ValueError as exc:
                evaluations.record_document_failure(evaluation_id, name, str(exc))
                continue

            # The extraction step leaves whatever the provider reported here.
            stats = result.artifacts.get("inference_stats") or {}
            pages = result.artifacts.get("document_ai_pages") or {}
            evaluations.record_document(
                evaluation_id,
                name,
                outcomes,
                elapsed_ms,
                prompt_tokens=stats.get("prompt_tokens"),
                completion_tokens=stats.get("completion_tokens"),
                ocr_pages=pages.get("document_ai_ocr"),
                layout_pages=pages.get("document_ai_layout"),
            )
            if run_store is not None:
                run_store.record_run(
                    filename=name,
                    content=content,
                    model=model,
                    prompts=prompts,
                    extraction=extraction,
                    page_count=result.artifacts["page_count"],
                    processed_pages=result.artifacts["processed_pages"],
                    elapsed_ms=elapsed_ms,
                    source="evaluation",
                    provider=provider,
                    pipeline=pipeline_name,
                    steps=pipeline_steps or [],
                )

        if cancelled is not None and cancelled.is_set():
            evaluations.finish(evaluation_id, "cancelled")
        else:
            evaluations.complete(evaluation_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the run must never die silently
        evaluations.finish(evaluation_id, "failed", error=str(exc))
        raise
