import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, AsyncIterator

import pymupdf
from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
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
    FieldLocation,
    ExtractionRun,
    ExtractionRunDetail,
    GcpKeyStatus,
    GeminiKeyStatus,
    HealthStatus,
    LabelsRequest,
    MetricTally,
    Metrics,
    ModelExecutionProfile,
    ModelInfo,
    RuntimeEngineInfo,
    ModelLoadRequest,
    ModelLoadResponse,
    ProcessingInfo,
    PromoteRunRequest,
    PipelineRenameRequest,
    PromptPreview,
    PromptPreviewRequest,
    SavedPipeline,
    MasterDataColumn,
    MasterDataRowRequest,
    MasterDataImport,
    SupplierRuleModel,
    SupplierRuleRequest,
    SupplierRuleUpdate,
    MasterDataTable,
    StepCatalogueEntry,
)
from app.evaluation.dataset_archive import ArchiveError, read_archive, write_archive
from app.evaluation.datasets import DatasetStore, InvalidName
from app.evaluation.export import evaluation_to_csv
from app.evaluation.runner import run_evaluation
from app.evaluation.store import EvaluationStore
from app.pipeline.compiler import PipelineError, build_steps
from app.pipeline.definition import (
    CONTRACTS,
    PipelineDefinition,
    describe_problems,
    describe_warnings,
    requires_vision,
    uses_model,
)
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.store import InvalidPipelineName, PipelineStore, UnknownPipeline
from app.services.document_ai import DocumentAiClient, DocumentAiError, ServiceAccount
from app.services.gemini import GEMINI_MODELS, GeminiClient, GeminiError, find_model
from app.services.lm_studio import (
    LMStudioClient,
    LMStudioError,
    MODEL_PROFILE_CONTEXT_LENGTH,
    MODEL_PROFILE_EVAL_BATCH_SIZE,
    MODEL_PROFILE_FLASH_ATTENTION,
    MODEL_PROFILE_OFFLOAD_KV_CACHE,
    MODEL_PROFILE_PARALLEL,
    MODEL_PROFILE_SEED,
    runtime_uses_gpu,
)
from app.services.run_store import RunStore
from app.services.master_data import (
    TABLES,
    DuplicateRow,
    MasterDataStore,
    UnknownRow,
    UnknownTable,
)
from app.services.master_data_csv import csv_to_rows, rows_to_csv
from app.services.migrations import adopt_legacy_page_limit, clear_inherited_model_default
from app.services.settings_store import SettingsStore
from app.services.supplier_rules import RULE_KINDS, SupplierRule, SupplierRuleStore
from app.services.text_boxes import locate_value


MAX_FILE_SIZE = 20 * 1024 * 1024
# A dataset archive is many PDFs at once, so it needs its own ceiling: ten
# documents at the single-file limit already exceed that one.
MAX_ARCHIVE_SIZE = 500 * 1024 * 1024
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
DATABASE_PATH = DATA_DIR / "docuflow.db"
DATASETS_PATH = DATA_DIR / "datasets"
PIPELINES_PATH = DATA_DIR / "pipelines"
# One fixed location, so the instructions in Settings can name a real path.
GCP_CREDENTIALS_PATH = DATA_DIR / "gcp-service-account.json"

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
master_data_store = MasterDataStore(DATABASE_PATH)
# Beside the register the rules key on, in the same database.
supplier_rule_store = SupplierRuleStore(DATABASE_PATH)
pipeline_store = PipelineStore(PIPELINES_PATH)
# The page limit used to be one number for the whole app; carry an existing
# install's value into the pipeline that inherits the job, then write the
# starting point out so it is an ordinary editable file.
adopt_legacy_page_limit(SETTINGS_PATH, pipeline_store)
clear_inherited_model_default(SETTINGS_PATH)
pipeline_store.seed_default()
model_runtime_states: dict[str, str] = {}
model_warmup_modes: dict[str, str] = {}
model_runtime_profiles: dict[str, str] = {}
active_model_operation: str | None = None
active_document_task: asyncio.Task[Any] | None = None
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
        elif model.loaded and not model.profile_matches:
            # Something loaded this model with another context/concurrency
            # profile. Large models may also need the host-specific CPU-safe
            # path, but even a small model is reloaded so two PCs do not silently
            # run different settings.
            runtime_state = "profile_mismatch"
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


def _hosted_models(settings: AppSettings) -> list[ModelInfo]:
    """Hosted models need no loading: a valid key is the whole readiness story."""
    ready = bool(settings.gemini.api_key.strip())
    return [
        ModelInfo(
            id=model.id,
            name=model.name,
            provider="gemini",
            loaded=ready,
            ready=ready,
            runtime_state="ready" if ready else "not_loaded",
        )
        for model in GEMINI_MODELS
    ]


def _unique_model_alias(model_id: str, available: list[ModelInfo]) -> ModelInfo | None:
    """Resolve the same installed model across LM Studio key formats.

    Some releases report `qwen3.5-0.8b`, others prefix the publisher and report
    `lmstudio-community/qwen3.5-0.8b`. Exact ids always win. A suffix is adopted
    only when it is unique, so two publishers shipping a model with the same
    basename are never silently conflated.
    """
    exact = next((model for model in available if model.id == model_id), None)
    if exact is not None:
        return exact
    leaf = model_id.rsplit("/", 1)[-1].casefold()
    matches = [model for model in available if model.id.rsplit("/", 1)[-1].casefold() == leaf]
    return matches[0] if len(matches) == 1 else None


async def _ensure_model_ready(
    settings: AppSettings, pipeline: PipelineDefinition | None = None
) -> Any | None:
    """Raise unless the configured model can answer right now.

    A hosted model is ready as soon as its key is present; a local one has to be
    in memory and warmed up, which costs a round trip to LM Studio to confirm.

    Given a pipeline, only if that pipeline calls a model at all. A Custom
    Extractor pipeline never sends the document to one, and holding its run back
    until an unrelated model is loaded would cost minutes and several gigabytes
    for nothing. Called without a pipeline — drafting labels asks the model
    directly, outside any — the model is always needed.
    """
    if pipeline is not None and not uses_model(pipeline):
        return None

    if settings.provider == "gemini":
        selected = find_model(settings.model)
        if selected is None:
            raise HTTPException(
                status_code=409,
                detail=f"{settings.model} is not one of the supported hosted models.",
            )
        if not settings.gemini.api_key.strip():
            raise HTTPException(
                status_code=409,
                detail="No Gemini API key is configured. Add one in LLM.",
            )
        return selected

    try:
        # Every installed model, not only the ones that can see: a text-only
        # model behind an OCR step is a legitimate choice, and looking for it
        # among the vision models found nothing and called it "not ready".
        available = await LMStudioClient(settings.lm_studio_url).list_models()
    except LMStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    selected = next((model for model in available if model.id == settings.model), None)
    if selected is not None and selected.loaded and not selected.profile_matches:
        profile_detail = (
            "The CPU-safe profile also holds this model's layers on the processor. "
            if selected.requires_safe_profile
            else ""
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"{settings.model} is loaded with context or concurrency settings that do not "
                "match DocuFlow's reproducible profile. "
                f"{profile_detail}Use Load & warm up in LLM to reload it consistently."
            ),
        )
    if selected is None or not selected.loaded or model_runtime_states.get(settings.model) != "ready":
        raise HTTPException(
            status_code=409,
            detail="The active model is not ready. Open LLM and use Load & warm up first.",
        )
    return selected


def _execution_profile(
    settings: AppSettings,
    pipeline: PipelineDefinition | None,
    selected: Any | None,
) -> ModelExecutionProfile | None:
    """Snapshot provider controls that are otherwise lost after a run."""
    if pipeline is not None and not uses_model(pipeline):
        return None
    if settings.provider == "gemini":
        supports_thinking = bool(getattr(selected, "supports_thinking", True))
        return ModelExecutionProfile(
            provider="gemini",
            profile="hosted",
            temperature=0,
            thinking_level=settings.gemini.thinking_level if supports_thinking else None,
        )

    runtime_profile = model_runtime_profiles.get(settings.model)
    if runtime_profile not in {"standard", "compatibility", "compatibility_partial"}:
        runtime_profile = (
            "compatibility" if getattr(selected, "requires_safe_profile", False) else "standard"
        )
    # The CLI path for a CPU-safe load controls context, concurrency and CPU
    # placement, but LM Studio does not expose the remaining load settings on
    # that path. Null records that limit instead of claiming they were applied.
    complete_load_controls = runtime_profile != "compatibility"
    return ModelExecutionProfile(
        provider="lm_studio",
        profile=runtime_profile,
        parameters=getattr(selected, "parameters", None),
        quantization=getattr(selected, "quantization", None),
        model_size_bytes=getattr(selected, "size_bytes", None),
        temperature=0,
        seed=MODEL_PROFILE_SEED,
        reasoning_effort="none",
        context_length=MODEL_PROFILE_CONTEXT_LENGTH,
        parallel=MODEL_PROFILE_PARALLEL,
        eval_batch_size=(MODEL_PROFILE_EVAL_BATCH_SIZE if complete_load_controls else None),
        flash_attention=(MODEL_PROFILE_FLASH_ATTENTION if complete_load_controls else None),
        offload_kv_cache_to_gpu=(
            MODEL_PROFILE_OFFLOAD_KV_CACHE if complete_load_controls else None
        ),
    )


def _recorded_model(settings: AppSettings, pipeline: PipelineDefinition) -> tuple[str, str]:
    """Name only a model the pipeline can actually call."""
    if not uses_model(pipeline):
        return "Not used", "none"
    return settings.model, settings.provider


def _pipeline_context(settings: AppSettings, filename: str, content: bytes) -> PipelineContext:
    return PipelineContext(
        filename=filename,
        content=content,
        model=settings.model,
        lm_studio_url=settings.lm_studio_url,
        provider=settings.provider,
        gemini_api_key=settings.gemini.api_key,
        gemini_thinking_level=settings.gemini.thinking_level,
        gcp_credentials_path=str(GCP_CREDENTIALS_PATH),
        gcp_project_id=settings.gcp.project_id,
        gcp_location=settings.gcp.location,
    )


def _masked(settings: AppSettings) -> AppSettings:
    """The key never leaves the backend; the UI works from the hint instead."""
    return settings.model_copy(
        update={"gemini": settings.gemini.model_copy(update={"api_key": ""})}
    )


def _key_status(settings: AppSettings, verified: list[str] | None = None) -> GeminiKeyStatus:
    key = settings.gemini.api_key.strip()
    return GeminiKeyStatus(
        configured=bool(key),
        hint=f"…{key[-4:]}" if len(key) >= 4 else ("…" if key else ""),
        verified_models=verified or [],
    )


def _busy_message() -> str:
    if active_model_operation == "processing":
        return "A document is currently being processed. Wait for it to finish before changing models."
    if active_model_operation == "evaluating":
        return (
            "An evaluation is running in Lab. Only one model operation can run at a "
            "time, so wait for it to finish or cancel it."
        )
    return "A model is currently loading or warming up. Wait until it is ready."


# -- this machine, and the models on it -------------------------------------

@app.get("/api/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    settings = settings_store.read()
    reason: str | None = None
    try:
        await LMStudioClient(settings.lm_studio_url).list_models()
        connected = True
    except LMStudioError as exc:
        connected = False
        reason = str(exc)
    return HealthStatus(
        status="ok" if connected else "degraded",
        lm_studio=connected,
        active_model=settings.model,
        lm_studio_error=reason,
    )


@app.get("/api/models", response_model=list[ModelInfo])
async def models() -> list[ModelInfo]:
    settings = settings_store.read()
    hosted = _hosted_models(settings)
    try:
        discovered = await LMStudioClient(settings.lm_studio_url).list_models(
            settings.excluded_model_ids
        )
    except LMStudioError as exc:
        # One provider being unreachable must not hide the other. Only report a
        # failure when there is nothing at all to choose from.
        if not hosted:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return hosted
    resolved = _unique_model_alias(settings.model, discovered)
    if settings.provider == "lm_studio" and resolved is not None and resolved.id != settings.model:
        # Discovery awaited the network. Re-read before writing so a prompt or
        # pipeline saved in the meantime is never replaced by this migration's
        # stale snapshot.
        latest = settings_store.read()
        if latest.provider == "lm_studio" and latest.model == settings.model:
            settings_store.write(latest.model_copy(update={"model": resolved.id}))
    return [*_models_with_runtime_state(discovered), *hosted]


@app.get("/api/runtime-engine", response_model=RuntimeEngineInfo)
async def runtime_engine() -> RuntimeEngineInfo:
    settings = settings_store.read()
    client = LMStudioClient(settings.lm_studio_url)
    engine = await client.selected_runtime()
    host = await client.host_capabilities()
    best = (
        max(host.accelerators, key=lambda adapter: adapter.memory_bytes)
        if host and host.accelerators
        else None
    )
    return RuntimeEngineInfo(
        engine=engine,
        uses_gpu=runtime_uses_gpu(engine),
        accelerator=best.name if best else None,
        accelerator_bytes=best.memory_bytes if best else None,
        accelerator_integrated=bool(best and best.integrated),
        offload_budget_bytes=host.offload_budget_bytes if host else None,
    )


@app.post("/api/models/load", response_model=ModelLoadResponse)
async def load_model(request: ModelLoadRequest) -> ModelLoadResponse:
    settings = settings_store.read()
    if find_model(request.model) is not None:
        raise HTTPException(
            status_code=400,
            detail="This model runs on Google's servers and does not need loading. "
            "Add an API key in LLM and it is ready.",
        )
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
            discovered = await client.list_models()
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
                warm_vision=requires_vision(_selected_pipeline(settings)),
            )
            for model_id in list(model_runtime_states):
                if model_id != request.model:
                    model_runtime_states[model_id] = "not_loaded"
                    model_runtime_profiles.pop(model_id, None)
            model_runtime_states[request.model] = "ready"
            model_warmup_modes[request.model] = str(result["warmup_mode"])
            model_runtime_profiles[request.model] = str(result["profile"])
            # Re-read rather than write back the snapshot this request
            # started with: a load takes minutes, and anything chosen in the
            # meantime — a pipeline, above all — would be reverted by it.
            settings_store.write(
                settings_store.read().model_copy(update={"model": request.model})
            )
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


# -- configuration: entities, prompts, the chosen model and pipeline --------

@app.get("/api/settings", response_model=AppSettings)
async def get_settings() -> AppSettings:
    return _masked(settings_store.read())


@app.post("/api/prompts/preview", response_model=PromptPreview)
async def preview_prompt(request: PromptPreviewRequest) -> PromptPreview:
    """Show exactly what the model will be sent.

    The prompt a user writes is only the opening: the app appends the entity
    list, the confidence rubric and the format rules, and builds a schema from
    the entities. Assembling it here rather than in the browser means the
    preview cannot drift away from what actually goes out.
    """
    import json as _json

    # Imported here, not through the module-level names: this is pure prompt
    # assembly with no network in it, and it must show the real formatting even
    # when the network clients are substituted.
    from app.services.gemini import GeminiClient as Gemini
    from app.services.lm_studio import LMStudioClient as LMStudio

    if request.provider == "gemini":
        return PromptPreview(
            provider="gemini",
            system_prompt=Gemini._system_prompt(request.prompts),
            generation_schema=_json.dumps(
                Gemini.generation_schema(request.prompts.entities), indent=2
            ),
        )
    return PromptPreview(
        provider="lm_studio",
        system_prompt=LMStudio._system_prompt(request.prompts),
        generation_schema=_json.dumps(
            LMStudio._generation_schema(request.prompts.entities), indent=2
        ),
        output_token_budget=LMStudio._output_token_budget(request.prompts.entities),
    )


@app.get("/api/settings/gemini", response_model=GeminiKeyStatus)
async def gemini_key_status() -> GeminiKeyStatus:
    return _key_status(settings_store.read())


@app.post("/api/settings/gemini/verify", response_model=GeminiKeyStatus)
async def verify_gemini_key() -> GeminiKeyStatus:
    """Ask Google what this key can see, so a bad key fails here and not mid-run."""
    settings = settings_store.read()
    if not settings.gemini.api_key.strip():
        raise HTTPException(status_code=400, detail="Add a Gemini API key first.")
    try:
        available = await GeminiClient(settings.gemini.api_key).list_models()
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    supported = {model.id for model in GEMINI_MODELS}
    return _key_status(settings, verified=[name for name in available if name in supported])


@app.delete("/api/settings/gemini", status_code=204, response_class=Response)
async def clear_gemini_key() -> Response:
    settings = settings_store.read()
    settings_store.write(
        settings.model_copy(update={"gemini": settings.gemini.model_copy(update={"api_key": ""})})
    )
    return Response(status_code=204)


@app.put("/api/settings", response_model=AppSettings)
async def update_settings(settings: AppSettings) -> AppSettings:
    previous_settings = settings_store.read()
    try:
        chosen_pipeline = pipeline_store.read(settings.pipeline)
    except (UnknownPipeline, InvalidPipelineName) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if settings.model in settings.excluded_model_ids:
        raise HTTPException(
            status_code=400,
            detail="The active model cannot also be excluded on this device",
        )

    # The key is write-only: an empty field means "leave the stored one alone",
    # which is what the masked value the UI holds always sends back.
    if not settings.gemini.api_key.strip():
        settings = settings.model_copy(
            update={
                "gemini": settings.gemini.model_copy(
                    update={"api_key": previous_settings.gemini.api_key}
                )
            }
        )

    if settings.provider == "gemini":
        if find_model(settings.model) is None:
            raise HTTPException(
                status_code=400,
                detail=f"{settings.model} is not one of the supported hosted models.",
            )
    else:
        # Prompts and entities must stay editable while LM Studio is down; only a
        # change of target model or endpoint needs the live model list.
        endpoint_changed = settings.lm_studio_url != previous_settings.lm_studio_url
        provider_changed = settings.provider != previous_settings.provider
        if settings.model != previous_settings.model or endpoint_changed or provider_changed:
            try:
                available = await LMStudioClient(settings.lm_studio_url).list_models()
            except LMStudioError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            chosen = next(
                (model for model in available if model.id == settings.model), None
            )
            if chosen is None:
                raise HTTPException(
                    status_code=400, detail="Select a model installed in LM Studio"
                )
            # Vision is only required by a pipeline that hands the model page
            # images; one that reads OCR text is better off without it.
            if requires_vision(chosen_pipeline) and not chosen.vision:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"'{chosen_pipeline.name}' sends page images to the model, and "
                        f"{settings.model} has no vision. Pick a vision model, or a "
                        "pipeline that reads text."
                    ),
                )
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
    if (
        requires_vision(chosen_pipeline)
        and model_runtime_states.get(saved.model) == "ready"
        and model_warmup_modes.get(saved.model) == "schema"
    ):
        # A model prepared behind OCR has never seen an image. Switching to a
        # vision pipeline must expose Warm up instead of charging projector
        # startup (or its failure) to the first document.
        model_runtime_states[saved.model] = "loaded"
    return _masked(saved)



def _selected_pipeline(settings: AppSettings) -> PipelineDefinition:
    try:
        return pipeline_store.read(settings.pipeline)
    except (UnknownPipeline, InvalidPipelineName) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _field_locations(artifacts: dict[str, Any]) -> list[FieldLocation]:
    """Where each extracted value sits on the page, when the page was read.

    Nothing here asks the model for coordinates: the tokens an OCR step left
    behind are searched for the value it answered. A pipeline with no OCR step
    leaves no tokens and therefore no locations, which is the honest answer
    rather than an empty rectangle.
    """
    # A Custom Extractor says where each value was; nothing else does, so
    # everything else has to search the tokens for it.
    reported = artifacts.get("field_locations") or []
    if reported:
        return [FieldLocation(**location) for location in reported]

    tokens = artifacts.get("ocr_tokens") or []
    extraction = artifacts.get("extraction") or {}
    if not tokens:
        return []

    located: list[FieldLocation] = []
    for entity, field in extraction.items():
        value = getattr(field, "value", None)
        found = locate_value(value, tokens)
        if found is None:
            continue
        located.append(
            FieldLocation(
                entity=entity,
                page=found.page,
                left=found.box.left,
                top=found.box.top,
                right=found.box.right,
                bottom=found.box.bottom,
            )
        )
    return located


def _document_pipeline(settings: AppSettings) -> DocumentPipeline:
    """The configured pipeline, compiled. Anything unusable is refused here.

    Compiling before a document is touched means a broken regex or a step that
    reads something nothing produced is a 400 on the request, not a run that
    dies halfway through a dataset.
    """
    try:
        return DocumentPipeline(
            build_steps(
                _selected_pipeline(settings),
                prompts=settings.prompts,
                entities=settings.prompts.entities,
                gcp=settings.gcp,
                master_data=master_data_store,
                supplier_rules=supplier_rule_store,
            )
        )
    except (UnknownPipeline, InvalidPipelineName, PipelineError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -- extracting one document ------------------------------------------------

@app.post("/api/documents/extract", response_model=ExtractionResponse)
async def extract_document(file: UploadFile = File(...)) -> ExtractionResponse:
    global active_document_task

    if file.content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="A PDF document is required")

    # Refuse a busy backend before reading up to 20 MB of upload body.
    if active_model_operation is not None:
        raise HTTPException(status_code=409, detail=_busy_message())

    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="The PDF exceeds the 20 MB limit")

    settings = settings_store.read()
    async with exclusive_model_operation("processing"):
        active_document_task = asyncio.current_task()
        try:
            pipeline_definition = _selected_pipeline(settings)
            selected_model = await _ensure_model_ready(settings, pipeline_definition)
            execution_profile = _execution_profile(
                settings, pipeline_definition, selected_model
            )
            recorded_model, recorded_provider = _recorded_model(settings, pipeline_definition)
            context = _pipeline_context(settings, file.filename or "invoice.pdf", content)
            pipeline = _document_pipeline(settings)
            started = time.perf_counter()
            try:
                result = await pipeline.run(context)
            except asyncio.CancelledError:
                # Cancelling the task closes an in-flight httpx request. LM
                # Studio sees the disconnect and stops generation; no later
                # pipeline step is allowed to run.
                raise HTTPException(status_code=499, detail="Document processing was cancelled")
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except (LMStudioError, GeminiError) as exc:
                if "terminated" in str(exc).lower() or "device was lost" in str(exc).lower():
                    model_runtime_states[settings.model] = "error"
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            run_id = run_store.record_run(
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
                locations=_field_locations(result.artifacts),
            )
        finally:
            active_document_task = None


@app.post("/api/documents/extract/cancel", status_code=202)
async def cancel_document_extraction() -> dict[str, str]:
    task = active_document_task
    if active_model_operation != "processing" or task is None or task.done():
        raise HTTPException(status_code=409, detail="No document is currently being processed.")
    task.cancel()
    return {"status": "cancelling"}


# --- datasets, master data and evaluation runs -------------------------------------------------------------


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
                "pipeline",
                "provider",
                "steps",
                "execution_profile",
                "succeeded_documents",
                "failed_documents",
                "pending_documents",
                "total_elapsed_ms",
                "average_elapsed_ms",
                "prompt_tokens",
                "completion_tokens",
                "ocr_pages",
                "layout_pages",
            )
        },
        metrics=_metrics_model(detail.metrics),
    )


def _require_dataset(name: str) -> None:
    if name not in {dataset.name for dataset in dataset_store.list_datasets()}:
        raise HTTPException(status_code=404, detail=f"No dataset named {name}")



def _saved_pipeline(definition: PipelineDefinition) -> SavedPipeline:
    return SavedPipeline(
        name=definition.name,
        description=definition.description,
        page_limit=definition.page_limit,
        steps=definition.steps,
        problems=describe_problems(definition),
        warnings=describe_warnings(definition, settings_store.read().prompts.entities),
    )


def _refuse_unusable(definition: PipelineDefinition) -> None:
    """Everything a saved pipeline must satisfy, in one place.

    Saving a pipeline that cannot run is allowed nowhere: the app reads these
    files back and runs them, and a file that only fails at run time turns a
    composition mistake into a failed dataset run an hour later.
    """
    settings = settings_store.read()
    try:
        build_steps(
            definition,
            prompts=settings.prompts,
            entities=settings.prompts.entities,
            gcp=settings.gcp,
            master_data=master_data_store,
            supplier_rules=supplier_rule_store,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _gcp_status(settings: AppSettings) -> GcpKeyStatus:
    try:
        account = ServiceAccount.load(GCP_CREDENTIALS_PATH)
    except DocumentAiError as exc:
        return GcpKeyStatus(configured=False, path=str(GCP_CREDENTIALS_PATH), problem=str(exc))
    return GcpKeyStatus(
        configured=True,
        path=str(GCP_CREDENTIALS_PATH),
        client_email=account.client_email,
        project_id=settings.gcp.project_id or account.project_id,
    )


# -- Google Cloud credentials, which live in a file rather than in settings -

@app.get("/api/settings/gcp", response_model=GcpKeyStatus)
async def gcp_key_status() -> GcpKeyStatus:
    """What the backend can say about the key file, and never its contents."""
    return _gcp_status(settings_store.read())


@app.post("/api/settings/gcp/verify", response_model=GcpKeyStatus)
async def verify_gcp_key() -> GcpKeyStatus:
    """Send one blank page to each configured processor and report who answered.

    A real call, because a key that parses is not a key that is allowed to use
    these processors. It costs one page per processor.
    """
    settings = settings_store.read()
    status = _gcp_status(settings)
    if not status.configured:
        return status

    client = DocumentAiClient(
        GCP_CREDENTIALS_PATH, settings.gcp.project_id, settings.gcp.location
    )
    configured = [
        ("OCR", settings.gcp.ocr_processor_id),
        ("Layout Parser", settings.gcp.layout_processor_id),
    ]
    verified: list[str] = []
    problems: list[str] = []
    probe = _blank_page_pdf()
    for label, processor_id in configured:
        if not processor_id.strip():
            problems.append(f"No {label} processor id is configured.")
            continue
        try:
            await client.process(processor_id, probe)
            verified.append(processor_id)
        except DocumentAiError as exc:
            problems.append(str(exc))

    return status.model_copy(
        update={"verified_processors": verified, "problem": " ".join(problems)}
    )


def _blank_page_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "DocuFlow connection check")
    try:
        return document.tobytes()
    finally:
        document.close()


# -- pipelines --------------------------------------------------------------

@app.get("/api/pipelines/steps", response_model=list[StepCatalogueEntry])
async def list_pipeline_steps() -> list[StepCatalogueEntry]:
    """What can go into a pipeline, and what each piece needs and leaves behind."""
    return [
        StepCatalogueEntry(
            kind=contract.kind.value,
            label=contract.label,
            description=contract.description,
            requires_all=[artifact.value for artifact in contract.requires_all],
            requires_any=[artifact.value for artifact in contract.requires_any],
            produces=[artifact.value for artifact in contract.produces],
        )
        for contract in CONTRACTS.values()
    ]


@app.get("/api/pipelines", response_model=list[SavedPipeline])
async def list_pipelines() -> list[SavedPipeline]:
    return [_saved_pipeline(definition) for definition in pipeline_store.list()]


@app.post("/api/pipelines/check", response_model=SavedPipeline)
async def check_pipeline(definition: PipelineDefinition) -> SavedPipeline:
    """Say what is wrong with a pipeline someone is still editing. Saves nothing."""
    return _saved_pipeline(definition)


@app.get("/api/pipelines/{name}", response_model=SavedPipeline)
async def get_pipeline(name: str) -> SavedPipeline:
    try:
        return _saved_pipeline(pipeline_store.read(name))
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownPipeline as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/pipelines/{name}", response_model=SavedPipeline)
async def save_pipeline(name: str, definition: PipelineDefinition) -> SavedPipeline:
    if name != definition.name:
        raise HTTPException(
            status_code=400,
            detail=f"This pipeline is saved as {name!r}; rename it in the body to move it.",
        )
    _refuse_unusable(definition)
    try:
        return _saved_pipeline(pipeline_store.save(definition))
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/pipelines/{name}", response_model=SavedPipeline)
async def rename_pipeline(name: str, request: PipelineRenameRequest) -> SavedPipeline:
    """Rename in place, carrying the selection with it.

    A rename that quietly left the app running the old name would be worse than
    refusing one, so the setting follows the file.
    """
    try:
        renamed = pipeline_store.rename(name, request.name)
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownPipeline as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    settings = settings_store.read()
    if settings.pipeline == name:
        settings_store.write(settings.model_copy(update={"pipeline": renamed.name}))
    return _saved_pipeline(renamed)


@app.delete("/api/pipelines/{name}", status_code=204, response_class=Response)
async def delete_pipeline(name: str) -> Response:
    if settings_store.read().pipeline == name:
        raise HTTPException(
            status_code=409,
            detail="That pipeline is in use. Select another one in Pipelines before deleting it.",
        )
    try:
        pipeline_store.delete(name)
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownPipeline as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


# -- the register, and the supplier rules that key on it --------------------

@app.get("/api/master-data/tables", response_model=list[MasterDataTable])
async def list_master_data_tables() -> list[MasterDataTable]:
    """What tables exist and what each column is, so the UI needs no copy of it."""
    return [
        MasterDataTable(
            key=table.key,
            label=table.label,
            description=table.description,
            id_column=table.id_column,
            seed_entity=table.seed_entity,
            match_column=table.match_column,
            columns=[
                MasterDataColumn(
                    key=column.key,
                    label=column.label,
                    hint=column.hint,
                    kind=column.kind,
                    editable=column.editable,
                    generated=column.generated,
                )
                for column in table.columns
            ],
        )
        for table in TABLES.values()
    ]


def _rule_model(rule: SupplierRule) -> SupplierRuleModel:
    return SupplierRuleModel(**asdict(rule))


@app.get("/api/supplier-rules", response_model=list[SupplierRuleModel])
async def list_supplier_rules(id_subject: str = "") -> list[SupplierRuleModel]:
    """Every rule, or the ones written for one supplier."""
    rules = (
        supplier_rule_store.for_supplier(id_subject.strip())
        if id_subject.strip()
        else supplier_rule_store.all()
    )
    return [_rule_model(rule) for rule in rules]


@app.post("/api/supplier-rules", response_model=SupplierRuleModel, status_code=201)
async def add_supplier_rule(request: SupplierRuleRequest) -> SupplierRuleModel:
    try:
        created = supplier_rule_store.add(SupplierRule(**request.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _rule_model(created)


@app.patch("/api/supplier-rules/{rule_id}", response_model=SupplierRuleModel)
async def update_supplier_rule(rule_id: int, request: SupplierRuleUpdate) -> SupplierRuleModel:
    try:
        updated = supplier_rule_store.update(
            rule_id, request.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No rule with id {rule_id}")
    return _rule_model(updated)


@app.delete("/api/supplier-rules/{rule_id}", status_code=204, response_class=Response)
async def delete_supplier_rule(rule_id: int) -> Response:
    supplier_rule_store.delete(rule_id)
    return Response(status_code=204)


@app.get("/api/master-data/tables/{table_key}/export.csv", response_class=Response)
async def export_master_data(table_key: str) -> Response:
    """The whole table as CSV, which is what a spreadsheet already speaks."""
    try:
        table = master_data_store.table(table_key)
        content = rows_to_csv(master_data_store, table_key)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{table.key}.csv"'},
    )


@app.post("/api/master-data/tables/{table_key}/import", response_model=MasterDataImport)
async def import_master_data(table_key: str, file: UploadFile = File(...)) -> MasterDataImport:
    """Add every row the file holds that the table can take.

    A row that cannot be stored is skipped and reported rather than failing the
    file, so importing a register that partly overlaps an existing one adds the
    part that is new.
    """
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="The file exceeds the 20 MB limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=415,
            detail="That file is not UTF-8 text, so its rows cannot be read.",
        ) from exc
    try:
        report = csv_to_rows(master_data_store, table_key, text)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MasterDataImport(added=report.added, skipped=report.skipped, reasons=report.reasons)


@app.get("/api/master-data/tables/{table_key}/rows", response_model=list[dict[str, Any]])
async def list_master_data_rows(
    table_key: str,
    query: str = "",
    sort: str = "",
    descending: bool = False,
    filter: Annotated[list[str], Query()] = [],
) -> list[dict[str, Any]]:
    """Rows, narrowed by a search over everything and by column.

    Each `filter` is `column:value`; the column name cannot contain a colon,
    so splitting once leaves any colon in the value alone.
    """
    filters: dict[str, str] = {}
    for item in filter:
        column, separator, value = item.partition(":")
        if separator:
            filters[column] = value
    try:
        return master_data_store.rows(
            table_key, query=query, sort=sort, descending=descending, filters=filters
        )
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/master-data/tables/{table_key}/rows", response_model=dict[str, Any], status_code=201)
async def add_master_data_row(table_key: str, request: MasterDataRowRequest) -> dict[str, Any]:
    try:
        return master_data_store.add(table_key, request.values)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateRow as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/master-data/tables/{table_key}/rows/from-datasets", response_model=list[dict[str, Any]])
async def seed_master_data_rows(table_key: str) -> list[dict[str, Any]]:
    """Fill a table from the labelled documents, adding only what is missing."""
    try:
        table = master_data_store.table(table_key)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not table.seed_entity:
        raise HTTPException(
            status_code=400,
            detail=f"{table.label} is not built from a labelled field.",
        )

    values: list[str] = []
    for dataset in dataset_store.list_datasets():
        for document in dataset_store.list_documents(dataset.name):
            label_file = dataset_store.read_labels(dataset.name, document.name)
            if label_file is None:
                continue
            value = label_file.labels.get(table.seed_entity)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    return master_data_store.seed(table_key, values)


@app.patch("/api/master-data/tables/{table_key}/rows/{identifier}", response_model=dict[str, Any])
async def update_master_data_row(
    table_key: str,
    identifier: str,
    request: MasterDataRowRequest,
) -> dict[str, Any]:
    try:
        return master_data_store.update(table_key, identifier, request.values)
    except (UnknownTable, UnknownRow) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateRow as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete(
    "/api/master-data/tables/{table_key}/rows/{identifier}",
    status_code=204,
    response_class=Response,
)
async def delete_master_data_row(table_key: str, identifier: str) -> Response:
    try:
        master_data_store.delete(table_key, identifier)
    except (UnknownTable, UnknownRow) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


# -- datasets and their ground truth ----------------------------------------

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


@app.get("/api/datasets/{name}/export.zip", response_class=Response)
async def export_dataset(name: str) -> Response:
    """The whole dataset as one file: the PDFs, their ground truth, a manifest."""
    _require_dataset(name)
    try:
        archive = write_archive(dataset_store, name)
    except ArchiveError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@app.post("/api/datasets/import", response_model=Dataset, status_code=201)
async def import_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> Dataset:
    """Create a dataset from an archive someone else exported.

    `name` overrides what the archive calls itself, which is how the same
    archive can be imported twice under two names, and how an archive that
    carries no manifest gets one at all.
    """
    content = await file.read(MAX_ARCHIVE_SIZE + 1)
    if len(content) > MAX_ARCHIVE_SIZE:
        limit = MAX_ARCHIVE_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=413, detail=f"The archive exceeds the {limit} MB limit"
        )
    try:
        summary = read_archive(dataset_store, content, name=(name or "").strip() or None)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ArchiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Dataset(**asdict(summary))


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


@app.get("/api/datasets/{name}/documents/{document}/file", response_class=Response)
async def read_dataset_document(name: str, document: str) -> Response:
    """Serve the PDF itself, so the reviewer can look at it while labelling."""
    _require_dataset(name)
    try:
        content = dataset_store.read_document(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"No document named {document}") from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{document}"'},
    )


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
    pipeline_definition = _selected_pipeline(settings)
    selected_model = await _ensure_model_ready(settings, pipeline_definition)
    execution_profile = _execution_profile(settings, pipeline_definition, selected_model)
    recorded_model, recorded_provider = _recorded_model(settings, pipeline_definition)

    try:
        content = dataset_store.read_document(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"No document named {document}") from exc

    async with exclusive_model_operation("processing"):
        context = _pipeline_context(settings, document, content)
        pipeline = _document_pipeline(settings)
        started = time.perf_counter()
        try:
            result = await pipeline.run(context)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (LMStudioError, GeminiError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        extraction = result.artifacts["extraction"]
        run_store.record_run(
            filename=document,
            content=content,
            model=recorded_model,
            prompts=settings.prompts,
            extraction=extraction,
            page_count=result.artifacts["page_count"],
            processed_pages=result.artifacts["processed_pages"],
            elapsed_ms=elapsed_ms,
            source="labelling",
            provider=recorded_provider,
            pipeline=settings.pipeline,
            steps=[step.kind.value for step in pipeline_definition.steps],
            execution_profile=execution_profile,
        )
        return DraftLabels(
            document=document,
            labels={name_: field.value for name_, field in extraction.items()},
            confidence={name_: field.confidence for name_, field in extraction.items()},
            elapsed_ms=elapsed_ms,
        )


# -- recorded runs ----------------------------------------------------------

@app.get("/api/runs", response_model=list[ExtractionRun])
async def list_runs(limit: int = 50, validated_only: bool = False) -> list[ExtractionRun]:
    return [
        ExtractionRun(**asdict(run))
        for run in run_store.list_runs(limit=min(limit, 200), validated_only=validated_only)
    ]


@app.get("/api/runs/{run_id}/pages/{page}.png", response_class=Response)
async def run_page_image(run_id: int, page: int) -> Response:
    """One page of a run's document, rendered.

    Highlighting needs a surface with known coordinates, and the browser's PDF
    viewer is not one: nothing outside it can know where it put the page. An
    image can be overlaid exactly, and the app already renders pages.
    """
    detail = run_store.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    content = run_store.read_document(detail.file_sha256)
    if content is None:
        raise HTTPException(status_code=404, detail="That run's document is no longer stored.")

    document = pymupdf.open(stream=content, filetype="pdf")
    try:
        if page < 0 or page >= document.page_count:
            raise HTTPException(status_code=404, detail=f"That document has no page {page + 1}")
        pixmap = document[page].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        rendered = pixmap.tobytes("png")
    finally:
        document.close()

    return Response(
        content=rendered,
        media_type="image/png",
        # Addressed by run and page, and a run's document never changes.
        headers={"Cache-Control": "private, max-age=86400"},
    )


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


# -- Lab: evaluations over a dataset ----------------------------------------

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
        pipeline_definition=detail.pipeline_definition,
        documents=[asdict(document) for document in detail.documents],
    )


@app.get("/api/evaluations/{evaluation_id}/export.csv", response_class=Response)
async def export_evaluation(evaluation_id: int) -> Response:
    detail = evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    filename = f"run-{evaluation_id}-{detail.dataset}.csv"
    return Response(
        content=evaluation_to_csv(detail),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

    # Compiled before anything is claimed: a pipeline that cannot run must
    # not leave the backend marked busy.
    pipeline_definition = _selected_pipeline(settings)
    steps = _document_pipeline(settings).steps

    selected_model = await _ensure_model_ready(settings, pipeline_definition)
    execution_profile = _execution_profile(settings, pipeline_definition, selected_model)
    recorded_model, recorded_provider = _recorded_model(settings, pipeline_definition)

    claim_model_operation("evaluating")
    evaluation_id = evaluation_store.start(
        dataset=request.dataset,
        model=recorded_model,
        prompts=settings.prompts,
        total_documents=len(documents),
        max_pages=pipeline_definition.page_limit,
        pipeline=settings.pipeline,
        provider=recorded_provider,
        steps=[step.kind.value for step in pipeline_definition.steps],
        pipeline_definition=pipeline_definition,
        execution_profile=execution_profile,
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
                model=recorded_model,
                provider=recorded_provider,
                max_pages=pipeline_definition.page_limit,
                steps=steps,
                pipeline_name=settings.pipeline,
                pipeline_steps=[step.kind.value for step in pipeline_definition.steps],
                execution_profile=execution_profile,
                make_context=lambda name, content: _pipeline_context(settings, name, content),
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

    The retry deliberately reuses the prompts, the model, the pipeline and the
    page limit the run was started with. Finishing a run with today's
    configuration would make its single accuracy number the average of two
    different experiments.
    """
    global evaluation_task, evaluation_cancelled

    detail = evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status == "running":
        raise HTTPException(status_code=409, detail="That evaluation is already running.")
    _require_dataset(detail.dataset)

    settings = settings_store.read()
    try:
        # New runs carry the complete definition. Legacy rows fall back to the
        # saved pipeline because the earlier schema retained only its name.
        definition = (
            detail.pipeline_definition.model_copy(deep=True)
            if detail.pipeline_definition is not None
            else pipeline_store.read(detail.pipeline)
        )
        page_limit = detail.max_pages or definition.page_limit
        definition.page_limit = page_limit
        steps = build_steps(
            definition,
            prompts=detail.prompts,
            entities=detail.prompts.entities,
            gcp=settings.gcp,
            master_data=master_data_store,
            supplier_rules=supplier_rule_store,
        )
    except (UnknownPipeline, InvalidPipelineName) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This run used the pipeline '{detail.pipeline}', which no longer exists. "
                "Recreate it to finish the run."
            ),
        ) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Which model is selected matters only to a pipeline that asks one. Read
    # after the pipeline, because a Custom Extractor run scores the same
    # whatever is loaded, and refusing to finish it over an unused model would
    # leave it half done for no reason.
    if uses_model(definition) and (
        settings.provider != detail.provider or settings.model != detail.model
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"This run used {detail.provider}/{detail.model}; the active selection is "
                f"{settings.provider}/{settings.model}. The retry was not started."
            ),
        )

    selected_model = await _ensure_model_ready(settings, definition)
    current_profile = _execution_profile(settings, definition, selected_model)
    if detail.execution_profile is not None and current_profile != detail.execution_profile:
        raise HTTPException(
            status_code=409,
            detail=(
                "The active model execution profile differs from the one recorded for this run. "
                "The retry was not started."
            ),
        )

    retry_settings = (
        settings.model_copy(update={"provider": detail.provider, "model": detail.model})
        if uses_model(definition)
        else settings
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
                provider=detail.provider,
                max_pages=page_limit,
                steps=steps,
                pipeline_name=detail.pipeline,
                pipeline_steps=detail.steps,
                execution_profile=detail.execution_profile,
                make_context=lambda name, content: _pipeline_context(
                    retry_settings, name, content
                ),
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


@app.post("/api/evaluations/{evaluation_id}/cancel", status_code=202, response_model=Evaluation)
async def cancel_evaluation(evaluation_id: int) -> Evaluation:
    detail = evaluation_store.get_evaluation(evaluation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No evaluation with id {evaluation_id}")
    if detail.status != "running":
        raise HTTPException(status_code=409, detail="That evaluation is not running.")
    if evaluation_cancelled is not None:
        evaluation_cancelled.set()
    # The event is inspected at document boundaries. Cancelling the task as
    # well propagates into the provider request, so a slow document does not
    # keep running for minutes after the user pressed Cancel.
    evaluation_store.finish(evaluation_id, "cancelled")
    if evaluation_task is not None and not evaluation_task.done():
        evaluation_task.cancel()
    return _evaluation_model(evaluation_store.get_evaluation(evaluation_id))
