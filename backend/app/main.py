import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.domain.models import (
    AppSettings,
    CorrectionsRequest,
    Dataset,
    DatasetCreateRequest,
    DatasetDocument,
    DocumentLabels,
    DraftLabels,
    Evaluation,
    EvaluationDetail,
    EvaluationRequest,
    ExtractionResponse,
    ExtractionRun,
    ExtractionRunDetail,
    HealthStatus,
    LabelsRequest,
    MetricTally,
    Metrics,
    ModelInfo,
    ModelLoadRequest,
    ModelLoadResponse,
    ProcessingInfo,
    PromoteRunRequest,
)
from app.evaluation.datasets import DatasetStore, InvalidName
from app.evaluation.runner import run_evaluation
from app.evaluation.store import EvaluationStore
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.steps import ExtractConfiguredEntities, InspectPdf
from app.services.lm_studio import LMStudioClient, LMStudioError
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore


MAX_FILE_SIZE = 20 * 1024 * 1024
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
DATABASE_PATH = DATA_DIR / "docuflow.db"
DATASETS_PATH = DATA_DIR / "datasets"

app = FastAPI(title="DocuFlow API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings_store = SettingsStore(SETTINGS_PATH)
run_store = RunStore(DATABASE_PATH)
evaluation_store = EvaluationStore(DATABASE_PATH)
dataset_store = DatasetStore(DATASETS_PATH)
model_runtime_states: dict[str, str] = {}
model_warmup_modes: dict[str, str] = {}
active_model_operation: str | None = None
evaluation_task: asyncio.Task | None = None
evaluation_cancelled: asyncio.Event | None = None

# A run still marked `running` belongs to a backend that no longer exists.
evaluation_store.mark_interrupted()


def claim_model_operation(phase: str) -> None:
    """Refuse, never queue, a second model operation.

    The busy check and the claim happen without an intervening await, so the
    event loop cannot interleave two callers between them. `asyncio.Lock` was
    deliberately avoided: a lock makes the second caller wait for work that can
    legitimately run for many minutes.
    """
    global active_model_operation

    if active_model_operation is not None:
        raise HTTPException(status_code=409, detail=_busy_message())
    active_model_operation = phase


def release_model_operation() -> None:
    global active_model_operation
    active_model_operation = None


@asynccontextmanager
async def exclusive_model_operation(phase: str) -> AsyncIterator[None]:
    claim_model_operation(phase)
    try:
        yield
    finally:
        release_model_operation()


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
    if active_model_operation == "evaluating":
        return (
            "An evaluation is running in Prompt Lab. Only one model operation can run at a "
            "time, so wait for it to finish or cancel it."
        )
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

        run_id = run_store.record_run(
            filename=context.filename,
            content=content,
            model=context.model,
            prompts=settings.prompts,
            extraction=result.artifacts["extraction"],
            page_count=result.artifacts["page_count"],
            processed_pages=result.artifacts["processed_pages"],
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            source="workspace",
        )

        return ExtractionResponse(
            run_id=run_id,
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


# --- Prompt Lab -------------------------------------------------------------


def _metrics_model(metrics: Any) -> Metrics:
    def tally(value: Any) -> MetricTally:
        return MetricTally(matched=value.matched, total=value.total, accuracy=value.accuracy)

    return Metrics(
        matched=metrics.matched,
        total=metrics.total,
        accuracy=metrics.accuracy,
        per_entity={name: tally(value) for name, value in metrics.per_entity.items()},
        per_confidence={name: tally(value) for name, value in metrics.per_confidence.items()},
    )


def _evaluation_model(detail: Any) -> Evaluation:
    return Evaluation(
        **{
            key: getattr(detail, key)
            for key in (
                "id",
                "created_at",
                "finished_at",
                "dataset",
                "model",
                "status",
                "total_documents",
                "completed_documents",
                "error",
                "max_pages",
                "succeeded_documents",
                "failed_documents",
                "pending_documents",
                "total_elapsed_ms",
                "average_elapsed_ms",
            )
        },
        metrics=_metrics_model(detail.metrics),
    )


def _require_dataset(name: str) -> None:
    if name not in {dataset.name for dataset in dataset_store.list_datasets()}:
        raise HTTPException(status_code=404, detail=f"No dataset named {name}")


@app.get("/api/datasets", response_model=list[Dataset])
async def list_datasets() -> list[Dataset]:
    return [Dataset(**asdict(dataset)) for dataset in dataset_store.list_datasets()]


@app.post("/api/datasets", response_model=Dataset, status_code=201)
async def create_dataset(request: DatasetCreateRequest) -> Dataset:
    try:
        return Dataset(**asdict(dataset_store.create(request.name)))
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch("/api/datasets/{name}", response_model=Dataset)
async def rename_dataset(name: str, request: DatasetCreateRequest) -> Dataset:
    try:
        return Dataset(**asdict(dataset_store.rename(name, request.name)))
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/datasets/{name}", status_code=204, response_class=Response)
async def delete_dataset(name: str) -> Response:
    try:
        dataset_store.delete(name)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@app.get("/api/datasets/{name}/documents", response_model=list[DatasetDocument])
async def list_dataset_documents(name: str) -> list[DatasetDocument]:
    _require_dataset(name)
    return [DatasetDocument(**asdict(document)) for document in dataset_store.list_documents(name)]


@app.post("/api/datasets/{name}/documents", response_model=DatasetDocument, status_code=201)
async def add_dataset_document(name: str, file: UploadFile = File(...)) -> DatasetDocument:
    _require_dataset(name)
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="The PDF exceeds the 20 MB limit")
    try:
        added = dataset_store.add_document(name, file.filename or "document.pdf", content)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return DatasetDocument(**asdict(added))


@app.delete("/api/datasets/{name}/documents/{document}", status_code=204, response_class=Response)
async def delete_dataset_document(name: str, document: str) -> Response:
    _require_dataset(name)
    try:
        dataset_store.remove_document(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@app.get("/api/datasets/{name}/documents/{document}/labels", response_model=DocumentLabels)
async def get_document_labels(name: str, document: str) -> DocumentLabels:
    _require_dataset(name)
    try:
        label_file = dataset_store.read_labels(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if label_file is None:
        return DocumentLabels(document=document, source="none", labels={})
    return DocumentLabels(
        document=document,
        source=label_file.source,
        labels=label_file.labels,
        updated_at=label_file.updated_at,
    )


@app.put("/api/datasets/{name}/documents/{document}/labels", response_model=DocumentLabels)
async def set_document_labels(name: str, document: str, request: LabelsRequest) -> DocumentLabels:
    _require_dataset(name)
    configured = {entity.name for entity in settings_store.read().prompts.entities}
    unknown = sorted(set(request.labels) - configured)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="These labels name entities that are not configured: " + ", ".join(unknown),
        )
    try:
        label_file = dataset_store.set_labels(name, document, request.labels, source="manual")
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentLabels(
        document=document,
        source=label_file.source,
        labels=label_file.labels,
        updated_at=label_file.updated_at,
    )


@app.post("/api/datasets/{name}/documents/from-run", response_model=list[DatasetDocument], status_code=201)
async def promote_runs_to_dataset(name: str, request: PromoteRunRequest) -> list[DatasetDocument]:
    _require_dataset(name)

    # Resolve everything first: a batch that names a missing run fails before it
    # has half-populated the dataset.
    resolved = []
    for run_id in request.run_ids:
        run = run_store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        content = run_store.read_document(run.file_sha256)
        if content is None:
            raise HTTPException(
                status_code=410,
                detail=f"The original PDF for run {run_id} is no longer stored on this device.",
            )
        resolved.append((run, content, run_store.validated_values(run_id) or {}))

    added: list[DatasetDocument] = []
    for run, content, labels in resolved:
        try:
            document = dataset_store.add_document(
                name, run.filename, content, labels=labels, source="promoted_run"
            )
        except InvalidName as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        added.append(DatasetDocument(**asdict(document)))
    return added


@app.post("/api/datasets/{name}/documents/{document}/draft-labels", response_model=DraftLabels)
async def draft_labels(name: str, document: str) -> DraftLabels:
    """Propose ground truth by running the active model. Nothing is saved.

    A blank labelling form for twenty invoices is why datasets never get built.
    A draft the reviewer corrects is the same work as reading the document once.
    """
    _require_dataset(name)
    settings = settings_store.read()

    try:
        available = await LMStudioClient(settings.lm_studio_url).list_vision_models()
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    selected = next((model for model in available if model.id == settings.model), None)
    if selected is None or not selected.loaded or model_runtime_states.get(settings.model) != "ready":
        raise HTTPException(
            status_code=409,
            detail="The active model is not ready. Open Settings and use Load & warm up first.",
        )

    try:
        content = dataset_store.read_document(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"No document named {document}") from exc

    async with exclusive_model_operation("processing"):
        context = PipelineContext(
            filename=document,
            content=content,
            model=settings.model,
            lm_studio_url=settings.lm_studio_url,
        )
        pipeline = DocumentPipeline(
            [
                InspectPdf(max_pages_to_analyze=settings.max_pages_to_analyze),
                ExtractConfiguredEntities(settings.prompts),
            ]
        )
        started = time.perf_counter()
        try:
            result = await pipeline.run(context)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LMStudioError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        extraction = result.artifacts["extraction"]
        run_store.record_run(
            filename=document,
            content=content,
            model=settings.model,
            prompts=settings.prompts,
            extraction=extraction,
            page_count=result.artifacts["page_count"],
            processed_pages=result.artifacts["processed_pages"],
            elapsed_ms=elapsed_ms,
            source="labelling",
        )
        return DraftLabels(
            document=document,
            labels={name_: field.value for name_, field in extraction.items()},
            confidence={name_: field.confidence for name_, field in extraction.items()},
            elapsed_ms=elapsed_ms,
        )


@app.get("/api/runs", response_model=list[ExtractionRun])
async def list_runs(limit: int = 50, validated_only: bool = False) -> list[ExtractionRun]:
    return [
        ExtractionRun(**asdict(run))
        for run in run_store.list_runs(limit=min(limit, 200), validated_only=validated_only)
    ]


@app.get("/api/runs/{run_id}", response_model=ExtractionRunDetail)
async def get_run(run_id: int) -> ExtractionRunDetail:
    run = run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    return ExtractionRunDetail(**asdict(run))


@app.post("/api/runs/{run_id}/corrections", status_code=204, response_class=Response)
async def record_corrections(run_id: int, request: CorrectionsRequest) -> Response:
    try:
        run_store.record_corrections(run_id, request.corrections)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@app.get("/api/evaluations", response_model=list[Evaluation])
async def list_evaluations() -> list[Evaluation]:
    return [_evaluation_model(evaluation) for evaluation in evaluation_store.list_evaluations()]


@app.get("/api/evaluations/{evaluation_id}", response_model=EvaluationDetail)
async def get_evaluation(evaluation_id: int) -> EvaluationDetail:
    detail = evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    summary = _evaluation_model(detail)
    return EvaluationDetail(
        **summary.model_dump(),
        prompts=detail.prompts,
        documents=[asdict(document) for document in detail.documents],
    )


@app.post("/api/evaluations", response_model=Evaluation, status_code=202)
async def start_evaluation(request: EvaluationRequest) -> Evaluation:
    global evaluation_task, evaluation_cancelled

    _require_dataset(request.dataset)
    settings = settings_store.read()

    documents: list[tuple[str, dict[str, Any]]] = []
    for document in dataset_store.list_documents(request.dataset):
        if not document.labelled:
            continue
        label_file = dataset_store.read_labels(request.dataset, document.name)
        if label_file is not None:
            documents.append((document.name, label_file.labels))
    if not documents:
        raise HTTPException(
            status_code=400,
            detail="This dataset has no labelled documents. Add ground truth before running a test.",
        )

    try:
        available = await LMStudioClient(settings.lm_studio_url).list_vision_models()
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    selected = next((model for model in available if model.id == settings.model), None)
    if selected is None or not selected.loaded or model_runtime_states.get(settings.model) != "ready":
        raise HTTPException(
            status_code=409,
            detail="The active model is not ready. Open Settings and use Load & warm up first.",
        )

    claim_model_operation("evaluating")
    evaluation_id = evaluation_store.start(
        dataset=request.dataset,
        model=settings.model,
        prompts=settings.prompts,
        total_documents=len(documents),
        max_pages=settings.max_pages_to_analyze,
    )
    evaluation_cancelled = asyncio.Event()

    async def drive(cancelled: asyncio.Event) -> None:
        try:
            await run_evaluation(
                evaluation_id=evaluation_id,
                evaluations=evaluation_store,
                datasets=dataset_store,
                run_store=run_store,
                dataset=request.dataset,
                documents=documents,
                entities=settings.prompts.entities,
                prompts=settings.prompts,
                model=settings.model,
                lm_studio_url=settings.lm_studio_url,
                max_pages=settings.max_pages_to_analyze,
                cancelled=cancelled,
            )
        except asyncio.CancelledError:
            evaluation_store.finish(evaluation_id, "cancelled")
        except Exception:
            # run_evaluation has already recorded the failure on the evaluation.
            pass
        finally:
            release_model_operation()

    evaluation_task = asyncio.create_task(drive(evaluation_cancelled))
    return _evaluation_model(evaluation_store.get_evaluation(evaluation_id))


@app.delete("/api/evaluations/{evaluation_id}", status_code=204, response_class=Response)
async def delete_evaluation(evaluation_id: int) -> Response:
    detail = evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status == "running":
        raise HTTPException(status_code=409, detail="Cancel that evaluation before deleting it.")
    evaluation_store.delete(evaluation_id)
    return Response(status_code=204)


@app.post("/api/evaluations/{evaluation_id}/retry", status_code=202, response_model=Evaluation)
async def retry_evaluation(evaluation_id: int) -> Evaluation:
    """Fill in the documents a run never scored, inside the same run.

    The retry deliberately reuses the prompts, the model and the page limit the
    run was started with. Finishing a run with today's configuration would make
    its single accuracy number the average of two different experiments.
    """
    global evaluation_task, evaluation_cancelled

    detail = evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status == "running":
        raise HTTPException(status_code=409, detail="That evaluation is already running.")
    _require_dataset(detail.dataset)

    settings = settings_store.read()
    if settings.model != detail.model:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This run used {detail.model}. Select and warm up that model in Settings, "
                "so the retried documents are scored the same way as the rest of the run."
            ),
        )
    try:
        available = await LMStudioClient(settings.lm_studio_url).list_vision_models()
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    selected = next((model for model in available if model.id == detail.model), None)
    if selected is None or not selected.loaded or model_runtime_states.get(detail.model) != "ready":
        raise HTTPException(
            status_code=409,
            detail="The active model is not ready. Open Settings and use Load & warm up first.",
        )

    attempted = evaluation_store.attempted_documents(evaluation_id)
    documents: list[tuple[str, dict[str, Any]]] = []
    for document in dataset_store.list_documents(detail.dataset):
        if not document.labelled or attempted.get(document.name) == "ok":
            continue
        label_file = dataset_store.read_labels(detail.dataset, document.name)
        if label_file is not None:
            documents.append((document.name, label_file.labels))
    if not documents:
        raise HTTPException(
            status_code=400,
            detail="This run has nothing left to process: every labelled document already succeeded.",
        )

    claim_model_operation("evaluating")
    evaluation_store.reopen(evaluation_id)
    evaluation_cancelled = asyncio.Event()

    async def drive(cancelled: asyncio.Event) -> None:
        try:
            await run_evaluation(
                evaluation_id=evaluation_id,
                evaluations=evaluation_store,
                datasets=dataset_store,
                run_store=run_store,
                dataset=detail.dataset,
                documents=documents,
                entities=detail.prompts.entities,
                prompts=detail.prompts,
                model=detail.model,
                lm_studio_url=settings.lm_studio_url,
                max_pages=detail.max_pages or settings.max_pages_to_analyze,
                cancelled=cancelled,
            )
        except asyncio.CancelledError:
            evaluation_store.finish(evaluation_id, "cancelled")
        except Exception:
            pass
        finally:
            release_model_operation()

    evaluation_task = asyncio.create_task(drive(evaluation_cancelled))
    return _evaluation_model(evaluation_store.get_evaluation(evaluation_id))


@app.post("/api/evaluations/{evaluation_id}/cancel", status_code=202, response_model=Evaluation)
async def cancel_evaluation(evaluation_id: int) -> Evaluation:
    detail = evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status != "running":
        raise HTTPException(status_code=409, detail="That evaluation is not running.")
    if evaluation_cancelled is not None:
        # Stops after the document in flight: killing a request mid-inference
        # leaves LM Studio busy with work nobody is waiting for.
        evaluation_cancelled.set()
    return _evaluation_model(evaluation_store.get_evaluation(evaluation_id))
