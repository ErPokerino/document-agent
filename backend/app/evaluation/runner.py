"""Run a whole dataset through the extraction pipeline and score the results.

One document is one full model call, so a dataset of twenty invoices is minutes
of work. This runs as a background task that reports progress into the store,
and a failure on one document is recorded and stepped over rather than losing
the whole run.
"""

import asyncio
import time
from typing import Any, Iterable

from app.domain.models import EntityDefinition, PromptConfiguration
from app.evaluation.datasets import DatasetStore
from app.evaluation.scoring import score_document
from app.evaluation.store import EvaluationStore
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.steps import ExtractConfiguredEntities, InspectPdf
from app.services.gemini import GeminiError
from app.services.lm_studio import LMStudioError
from app.services.run_store import RunStore


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
    lm_studio_url: str,
    max_pages: int,
    provider: str = "lm_studio",
    gemini_api_key: str = "",
    gemini_thinking_level: str = "low",
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
                context = PipelineContext(
                    filename=name,
                    content=content,
                    model=model,
                    lm_studio_url=lm_studio_url,
                    provider=provider,
                    gemini_api_key=gemini_api_key,
                    gemini_thinking_level=gemini_thinking_level,
                )
                pipeline = DocumentPipeline(
                    [
                        InspectPdf(max_pages_to_analyze=max_pages),
                        ExtractConfiguredEntities(prompts),
                    ]
                )
                result = await pipeline.run(context)
            except asyncio.CancelledError:
                evaluations.finish(evaluation_id, "cancelled")
                raise
            except (OSError, ValueError, LMStudioError, GeminiError) as exc:
                evaluations.record_document_failure(evaluation_id, name, str(exc))
                continue

            elapsed_ms = round((time.perf_counter() - started) * 1000)
            extraction = result.artifacts["extraction"]
            try:
                outcomes = score_document(entities, labels, extraction)
            except ValueError as exc:
                evaluations.record_document_failure(evaluation_id, name, str(exc))
                continue

            evaluations.record_document(evaluation_id, name, outcomes, elapsed_ms)
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
                )

        evaluations.complete(evaluation_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the run must never die silently
        evaluations.finish(evaluation_id, "failed", error=str(exc))
        raise
