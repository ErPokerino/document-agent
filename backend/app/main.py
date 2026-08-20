import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.domain.models import (
    AppSettings,
    ExtractionResponse,
    HealthStatus,
    ModelInfo,
    ModelLoadRequest,
    ModelLoadResponse,
    ProcessingInfo,
)
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.steps import ExtractConfiguredEntities, InspectPdf
from app.services.lm_studio import LMStudioClient, LMStudioError
from app.services.settings_store import SettingsStore


MAX_FILE_SIZE = 20 * 1024 * 1024
SETTINGS_PATH = Path(__file__).resolve().parents[1] / "data" / "settings.json"

app = FastAPI(title="DocuFlow API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings_store = SettingsStore(SETTINGS_PATH)
model_runtime_states: dict[str, str] = {}
model_warmup_modes: dict[str, str] = {}
active_model_operation: str | None = None


@asynccontextmanager
async def exclusive_model_operation(phase: str) -> AsyncIterator[None]:
    """Refuse, never queue, a second model operation.

    The busy check and the claim happen without an intervening await, so the
    event loop cannot interleave two callers between them. `asyncio.Lock` was
    deliberately avoided: a lock makes the second caller wait for an inference
    that can legitimately run for ten minutes.
    """
    global active_model_operation

    if active_model_operation is not None:
        raise HTTPException(status_code=409, detail=_busy_message())
    active_model_operation = phase
    try:
        yield
    finally:
        active_model_operation = None


def _models_with_runtime_state(models: list[ModelInfo]) -> list[ModelInfo]:
    enriched: list[ModelInfo] = []
    for model in models:
        tracked = model_runtime_states.get(model.id)
        if tracked in {"loading", "warming_up", "error"}:
            runtime_state = tracked
        elif tracked == "ready" and model.loaded:
            runtime_state = "ready"
        elif model.loaded:
            runtime_state = "loaded"
        else:
            runtime_state = "not_loaded"
        enriched.append(
            model.model_copy(
                update={
                    "runtime_state": runtime_state,
                    "ready": runtime_state == "ready",
                }
            )
        )
    return enriched


def _busy_message() -> str:
    if active_model_operation == "processing":
        return "A document is currently being processed. Wait for it to finish before changing models."
    return "A model is currently loading or warming up. Wait until it is ready."


@app.get("/api/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    settings = settings_store.read()
    try:
        await LMStudioClient(settings.lm_studio_url).list_vision_models()
        connected = True
    except LMStudioError:
        connected = False
    return HealthStatus(
        status="ok" if connected else "degraded",
        lm_studio=connected,
        active_model=settings.model,
    )


@app.get("/api/models", response_model=list[ModelInfo])
async def models() -> list[ModelInfo]:
    settings = settings_store.read()
    try:
        discovered = await LMStudioClient(settings.lm_studio_url).list_vision_models(
            settings.excluded_model_ids
        )
        return _models_with_runtime_state(discovered)
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/models/load", response_model=ModelLoadResponse)
async def load_model(request: ModelLoadRequest) -> ModelLoadResponse:
    settings = settings_store.read()
    if request.model in settings.excluded_model_ids:
        raise HTTPException(
            status_code=400,
            detail="This model is excluded on this device because it did not pass local compatibility testing.",
        )
    client = LMStudioClient(settings.lm_studio_url)
    async with exclusive_model_operation("loading"):
        previous_runtime_state = model_runtime_states.get(request.model)
        model_runtime_states[request.model] = "loading"

        def update_phase(phase: str) -> None:
            global active_model_operation
            active_model_operation = phase
            model_runtime_states[request.model] = phase

        try:
            discovered = await client.list_vision_models()
            selected = next((model for model in discovered if model.id == request.model), None)
            already_ready = bool(
                selected
                and selected.loaded
                and previous_runtime_state == "ready"
            )
            result = await client.load_and_warm_model(
                request.model,
                skip_warmup=already_ready,
                phase_callback=update_phase,
                entities=settings.prompts.entities,
            )
            for model_id in list(model_runtime_states):
                if model_id != request.model:
                    model_runtime_states[model_id] = "not_loaded"
            model_runtime_states[request.model] = "ready"
            model_warmup_modes[request.model] = str(result["warmup_mode"])
            settings_store.write(settings.model_copy(update={"model": request.model}))
            return ModelLoadResponse.model_validate(result)
        except LMStudioError as exc:
            model_runtime_states[request.model] = "error"
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except BaseException:
            # Includes CancelledError, raised whenever the browser tab is closed
            # during a multi-minute load. Without this the model would stay
            # "loading" forever and both Load and Extract would refuse to run.
            model_runtime_states[request.model] = "error"
            raise


@app.get("/api/settings", response_model=AppSettings)
async def get_settings() -> AppSettings:
    return settings_store.read()


@app.put("/api/settings", response_model=AppSettings)
async def update_settings(settings: AppSettings) -> AppSettings:
    previous_settings = settings_store.read()
    if settings.model in settings.excluded_model_ids:
        raise HTTPException(
            status_code=400,
            detail="The active model cannot also be excluded on this device",
        )
    # Prompts and entities must stay editable while LM Studio is down; only a
    # change of target model or endpoint needs the live model list.
    endpoint_changed = settings.lm_studio_url != previous_settings.lm_studio_url
    if settings.model != previous_settings.model or endpoint_changed:
        try:
            available = await LMStudioClient(settings.lm_studio_url).list_vision_models()
        except LMStudioError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if settings.model not in {model.id for model in available}:
            raise HTTPException(status_code=400, detail="Select a vision-capable model")
    saved = settings_store.write(settings)
    previous_schema = [
        (entity.name, entity.format) for entity in previous_settings.prompts.entities
    ]
    new_schema = [(entity.name, entity.format) for entity in saved.prompts.entities]
    if (
        previous_schema != new_schema
        and model_runtime_states.get(saved.model) == "ready"
        and model_warmup_modes.get(saved.model) == "vision_and_schema"
    ):
        model_runtime_states[saved.model] = "loaded"
    return saved


@app.post("/api/documents/extract", response_model=ExtractionResponse)
async def extract_document(file: UploadFile = File(...)) -> ExtractionResponse:
    if file.content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="A PDF document is required")

    # Refuse a busy backend before reading up to 20 MB of upload body.
    if active_model_operation is not None:
        raise HTTPException(status_code=409, detail=_busy_message())

    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="The PDF exceeds the 20 MB limit")

    settings = settings_store.read()
    client = LMStudioClient(settings.lm_studio_url)
    async with exclusive_model_operation("processing"):
        try:
            available_models = await client.list_vision_models()
        except LMStudioError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        selected_model = next(
            (model for model in available_models if model.id == settings.model),
            None,
        )
        if (
            selected_model is None
            or not selected_model.loaded
            or model_runtime_states.get(settings.model) != "ready"
        ):
            raise HTTPException(
                status_code=409,
                detail="The active model is not ready. Open Settings and use Load & warm up first.",
            )

        context = PipelineContext(
            filename=file.filename or "invoice.pdf",
            content=content,
            model=settings.model,
            lm_studio_url=settings.lm_studio_url,
        )
        pipeline = DocumentPipeline(
            [
                InspectPdf(
                    max_pages_to_analyze=settings.max_pages_to_analyze,
                ),
                ExtractConfiguredEntities(settings.prompts),
            ]
        )
        started = time.perf_counter()
        try:
            result = await pipeline.run(context)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LMStudioError as exc:
            if "terminated" in str(exc).lower() or "device was lost" in str(exc).lower():
                model_runtime_states[settings.model] = "error"
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return ExtractionResponse(
            filename=context.filename,
            model=context.model,
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
        )
