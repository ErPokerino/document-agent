"""Extracting one document."""

import asyncio
import time

from fastapi import File, HTTPException, UploadFile, APIRouter

from app.api import deps
from app.domain.models import ExtractionResponse, PipelineActivity, ProcessingInfo
from app.pipeline.engine import step_name
from app.services.lm_studio import LMStudioError

router = APIRouter()


@router.post("/api/documents/extract", response_model=ExtractionResponse)
async def extract_document(file: UploadFile = File(...)) -> ExtractionResponse:
    if file.content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="A PDF document is required")

    # Refuse a busy backend before reading up to 20 MB of upload body.
    if deps.active_model_operation is not None:
        raise HTTPException(status_code=409, detail=deps.busy_message())

    content = await file.read(deps.MAX_FILE_SIZE + 1)
    if len(content) > deps.MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="The PDF exceeds the 20 MB limit")

    settings = deps.settings_store.read()
    async with deps.exclusive_model_operation("processing"):
        deps.active_document_task = asyncio.current_task()
        try:
            pipeline_definition = deps.selected_pipeline(settings)
            selected_model = await deps.ensure_model_ready(settings, pipeline_definition)
            execution_profile = deps.execution_profile(
                settings, pipeline_definition, selected_model
            )
            recorded_model, recorded_provider = deps.recorded_model(settings, pipeline_definition)
            context = deps.pipeline_context(settings, file.filename or "invoice.pdf", content)
            pipeline = deps.document_pipeline(settings)
            started = time.perf_counter()
            try:
                result = await pipeline.run(
                    context,
                    on_step=lambda step: deps.pipeline_activity.__setitem__("step", step_name(step)),
                )
            except asyncio.CancelledError:
                # Cancelling the task closes an in-flight httpx request. LM
                # Studio sees the disconnect and stops generation; no later
                # pipeline step is allowed to run.
                raise HTTPException(status_code=499, detail="Document processing was cancelled")
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except LMStudioError as exc:
                if exc.runtime_lost:
                    deps.model_runtime_states[settings.model] = "error"
                raise

            run_id = await asyncio.to_thread(
                deps.run_store.record_run,
                filename=context.filename,
                content=content,
                model=recorded_model,
                prompts=settings.prompts,
                extraction=result.artifacts["extraction"],
                page_count=result.artifacts["page_count"],
                processed_pages=result.artifacts["processed_pages"],
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                source="workspace",
                provider=recorded_provider,
                pipeline=settings.pipeline,
                steps=[step.kind.value for step in pipeline_definition.steps],
                execution_profile=execution_profile,
            )

            return ExtractionResponse(
                run_id=run_id,
                filename=context.filename,
                model=recorded_model,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                data=result.artifacts["extraction"],
                processing=ProcessingInfo(
                    page_count=result.artifacts["page_count"],
                    processed_pages=result.artifacts["processed_pages"],
                    first_processed_page=result.artifacts["first_processed_page"],
                    last_processed_page=result.artifacts["last_processed_page"],
                    cut_applied=result.artifacts["cut_applied"],
                    single_call_page_limit=result.artifacts["page_limit"],
                    configured_page_limit=result.artifacts["configured_page_limit"],
                    **result.artifacts.get("inference_stats", {}),
                ),
                locations=deps.field_locations(result.artifacts),
            )
        finally:
            deps.active_document_task = None
            deps.pipeline_activity["step"] = None


@router.get("/api/activity", response_model=PipelineActivity)
async def pipeline_activity() -> PipelineActivity:
    return PipelineActivity(step=deps.pipeline_activity["step"])


@router.post("/api/documents/extract/cancel", status_code=202)
async def cancel_document_extraction() -> dict[str, str]:
    task = deps.active_document_task
    if deps.active_model_operation != "processing" or task is None or task.done():
        raise HTTPException(status_code=409, detail="No document is currently being processed.")
    task.cancel()
    return {"status": "cancelling"}
