"""What every router shares: the stores, the state of the model runtime, and the
helpers that read both.

Routers reach all of it through this module (`deps.settings_store`, not a copy
of it), so replacing a store or a client here replaces it for every endpoint.
That is how the tests isolate the app from the data on this machine, and why
`GeminiClient`, `LMStudioClient` and `run_evaluation` are called as
`deps.<name>` rather than imported by each router.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator

import pymupdf
from fastapi import HTTPException

from app.domain.models import (
    MODEL_NOT_USED,
    AppSettings,
    Evaluation,
    FieldLocation,
    GcpKeyStatus,
    GeminiKeyStatus,
    MetricTally,
    Metrics,
    ModelExecutionProfile,
    ModelInfo,
    SavedPipeline,
    SupplierRuleModel,
)
from app.evaluation.datasets import DatasetStore
from app.evaluation.runner import run_evaluation
from app.evaluation.store import EvaluationStore
from app.pipeline.compiler import PipelineError, build_steps
from app.pipeline.definition import (
    PipelineDefinition,
    describe_problems,
    describe_warnings,
    uses_model,
)
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.store import InvalidPipelineName, PipelineStore, UnknownPipeline
from app.services.document_ai import DocumentAiClient, DocumentAiError, ServiceAccount
from app.services.gemini import GEMINI_MODELS, GeminiClient, find_model
from app.services.lm_studio import (
    LMStudioClient,
    LMStudioError,
    MODEL_PROFILE_CONTEXT_LENGTH,
    MODEL_PROFILE_EVAL_BATCH_SIZE,
    MODEL_PROFILE_FLASH_ATTENTION,
    MODEL_PROFILE_OFFLOAD_KV_CACHE,
    MODEL_PROFILE_PARALLEL,
    MODEL_PROFILE_SEED,
)
from app.services.master_data import MasterDataStore
from app.services.migrations import (
    adopt_legacy_page_limit,
    clear_inherited_model_default,
)
from app.services.processors import migrate_processor_catalog
from app.services.reading_cache import ReadingCache
from app.training.artifacts import ArtifactStore, UnknownArtifact, InvalidArtifact, training_hashes
from app.training.jobs import TrainingJobs
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore
from app.services.supplier_rules import SupplierRule, SupplierRuleStore
from app.services.text_boxes import locate_value


MAX_FILE_SIZE = 20 * 1024 * 1024
# A dataset archive is many PDFs at once, so it needs its own ceiling: ten
# documents at the single-file limit already exceed that one.
MAX_ARCHIVE_SIZE = 500 * 1024 * 1024
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"
DATABASE_PATH = DATA_DIR / "docuflow.db"
DATASETS_PATH = DATA_DIR / "datasets"
PIPELINES_PATH = DATA_DIR / "pipelines"
# One fixed location, so the instructions in Settings can name a real path.
GCP_CREDENTIALS_PATH = DATA_DIR / "gcp-service-account.json"
READING_CACHE_PATH = DATA_DIR / "reading-cache"
ARTIFACTS_PATH = DATA_DIR / "artifacts"
EXPORTS_PATH = DATA_DIR / "training-exports"
settings_store = SettingsStore(SETTINGS_PATH)
run_store = RunStore(DATABASE_PATH)
evaluation_store = EvaluationStore(DATABASE_PATH)
dataset_store = DatasetStore(DATASETS_PATH)
master_data_store = MasterDataStore(DATABASE_PATH)
# Beside the register the rules key on, in the same database.
supplier_rule_store = SupplierRuleStore(DATABASE_PATH)
pipeline_store = PipelineStore(PIPELINES_PATH)
reading_cache = ReadingCache(READING_CACHE_PATH)
artifact_store = ArtifactStore(ARTIFACTS_PATH)
training_jobs = TrainingJobs()
# The page limit used to be one number for the whole app; carry an existing
# install's value into the pipeline that inherits the job, then write the
# starting point out so it is an ordinary editable file.
adopt_legacy_page_limit(SETTINGS_PATH, pipeline_store)
clear_inherited_model_default(SETTINGS_PATH)
pipeline_store.seed_default()
migrate_processor_catalog(settings_store, pipeline_store)
model_runtime_states: dict[str, str] = {}
model_warmup_modes: dict[str, str] = {}
model_runtime_profiles: dict[str, str] = {}
active_model_operation: str | None = None
active_document_task: asyncio.Task[Any] | None = None
# The step inside the workspace request. Lab runs report theirs on the evaluation row.
pipeline_activity: dict[str, str | None] = {"step": None}
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
        raise HTTPException(status_code=409, detail=busy_message())
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


def models_with_runtime_state(models: list[ModelInfo]) -> list[ModelInfo]:
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


def hosted_models(settings: AppSettings) -> list[ModelInfo]:
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


def unique_model_alias(model_id: str, available: list[ModelInfo]) -> ModelInfo | None:
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


async def ensure_model_ready(
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


def execution_profile(
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


def recorded_model(settings: AppSettings, pipeline: PipelineDefinition) -> tuple[str, str]:
    """Name only a model the pipeline can actually call."""
    if not uses_model(pipeline):
        return MODEL_NOT_USED, "none"
    return settings.model, settings.provider


def pipeline_context(
    settings: AppSettings, filename: str, content: bytes, *, reuse_readings: bool = False
) -> PipelineContext:
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
        reading_cache=reading_cache,
        reuse_readings=reuse_readings,
    )


def masked(settings: AppSettings) -> AppSettings:
    """The key never leaves the backend; the UI works from the hint instead."""
    return settings.model_copy(
        update={"gemini": settings.gemini.model_copy(update={"api_key": ""})}
    )


def key_status(settings: AppSettings, verified: list[str] | None = None) -> GeminiKeyStatus:
    key = settings.gemini.api_key.strip()
    return GeminiKeyStatus(
        configured=bool(key),
        hint=f"…{key[-4:]}" if len(key) >= 4 else ("…" if key else ""),
        verified_models=verified or [],
    )


def busy_message() -> str:
    if active_model_operation == "processing":
        return "A document is currently being processed. Wait for it to finish before changing models."
    if active_model_operation == "evaluating":
        return (
            "An evaluation is running in Lab. Only one model operation can run at a "
            "time, so wait for it to finish or cancel it."
        )
    return "A model is currently loading or warming up. Wait until it is ready."


def selected_pipeline(settings: AppSettings) -> PipelineDefinition:
    try:
        from app.services.processors import resolved_pipeline
        return resolved_pipeline(pipeline_store.read(settings.pipeline), settings.gcp)
    except (UnknownPipeline, InvalidPipelineName, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def field_locations(artifacts: dict[str, Any]) -> list[FieldLocation]:
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


def document_pipeline(settings: AppSettings) -> DocumentPipeline:
    """The configured pipeline, compiled. Anything unusable is refused here.

    Compiling before a document is touched means a broken regex or a step that
    reads something nothing produced is a 400 on the request, not a run that
    dies halfway through a dataset.
    """
    try:
        return DocumentPipeline(
            build_steps(
                selected_pipeline(settings),
                prompts=settings.prompts,
                entities=settings.prompts.entities,
                gcp=settings.gcp,
                master_data=master_data_store,
                supplier_rules=supplier_rule_store,
                artifacts=artifact_store,
            )
        )
    except (UnknownPipeline, InvalidPipelineName, PipelineError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def metrics_model(metrics: Any) -> Metrics:
    def tally(value: Any) -> MetricTally:
        return MetricTally(matched=value.matched, total=value.total, accuracy=value.accuracy)

    return Metrics(
        matched=metrics.matched,
        total=metrics.total,
        accuracy=metrics.accuracy,
        per_entity={name: tally(value) for name, value in metrics.per_entity.items()},
        per_confidence={name: tally(value) for name, value in metrics.per_confidence.items()},
    )


def evaluation_model(detail: Any) -> Evaluation:
    definition = getattr(detail, "pipeline_definition", None)
    return Evaluation(
        processor_bindings=[step for step in definition.steps if step.kind.value.startswith("document_ai_") and step.config.get("project_id") and step.config.get("processor_id")] if definition else [],
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
                "custom_extractor_pages",
                "usage_complete",
                "extraction_engine",
                "fingerprint",
                "current_step",
                "reuse_readings",
                "cached_pages",
            )
        },
        metrics=metrics_model(detail.metrics),
    )


def require_dataset(name: str) -> None:
    if name not in {dataset.name for dataset in dataset_store.list_datasets()}:
        raise HTTPException(status_code=404, detail=f"No dataset named {name}")


def saved_pipeline(definition: PipelineDefinition) -> SavedPipeline:
    from app.services.processors import binding, KINDS
    settings = settings_store.read()
    problems = describe_problems(definition)
    for index, step in enumerate(definition.steps, start=1):
        if step.kind.value in KINDS:
            try:
                binding(step, settings.gcp)
            except ValueError as exc:
                problems.append(f"Step {index}: {exc}")
    return SavedPipeline(
        name=definition.name,
        description=definition.description,
        page_limit=definition.page_limit,
        steps=definition.steps,
        problems=problems,
        warnings=[
            *describe_warnings(definition, settings_store.read().prompts.entities),
            *reading_warnings(resolved_for_reading(definition, settings.gcp)),
        ],
    )


def resolved_for_reading(definition: PipelineDefinition, gcp: Any) -> PipelineDefinition:
    from app.services.processors import resolved_pipeline

    try:
        return resolved_pipeline(definition, gcp)
    except ValueError:
        return definition


def refuse_unusable(definition: PipelineDefinition) -> None:
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
            artifacts=artifact_store,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def trained_models_in(definition: PipelineDefinition) -> list[Any]:
    """The stored models a pipeline's steps name, those that still exist."""
    found = []
    for step in definition.steps:
        if step.kind.value != "artifact_predict":
            continue
        try:
            found.append(artifact_store.get(str(step.config.get("artifact_id") or "")))
        except (UnknownArtifact, InvalidArtifact):
            continue
    return found


def refuse_seen_documents(definition: PipelineDefinition, dataset: str, dataset_snapshot: dict[str, Any]) -> None:
    """A model is not scored on the documents it learned from.

    A nearest-neighbour model asked about a document it was trained on finds
    that very document at similarity 1 and copies its labels, so the run would
    report the labels back as accuracy.
    """
    hashes = {str(entry["sha256"]) for entry in dataset_snapshot.values()}
    for stored in trained_models_in(definition):
        seen = hashes & training_hashes(stored.manifest)
        if seen:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{len(seen)} of the {len(hashes)} documents in '{dataset}' were used to train "
                    f"'{stored.manifest.get('name') or stored.id}'. A run over them would score the "
                    "model on documents it has already seen."
                ),
            )


def reading_warnings(definition: PipelineDefinition) -> list[str]:
    """A trained model served text read another way than the text it learned from."""
    from app.training.corpus import reader_signature, same_reading, READER_KINDS
    from app.pipeline.definition import Artifact, contract_for

    warnings = []
    for index, step in enumerate(definition.steps, start=1):
        if step.kind.value != "artifact_predict":
            continue
        try:
            stored = artifact_store.get(str(step.config.get("artifact_id") or ""))
        except (UnknownArtifact, InvalidArtifact):
            continue
        before = []
        for earlier in definition.steps[: index - 1]:
            if Artifact.entities in contract_for(earlier.kind).produces:
                break
            if earlier.kind in READER_KINDS:
                before.append(earlier)
        recorded = (stored.manifest.get("training") or {}).get("reader") or []
        if recorded and not same_reading(recorded, reader_signature(before)):
            learned = " → ".join(entry["kind"] for entry in recorded)
            served = " → ".join(earlier.kind.value for earlier in before) or "nothing"
            warnings.append(
                f"Step {index} uses '{stored.manifest.get('name') or stored.id}', which learned from text read by "
                f"{learned}; here the text is read by {served}. Its similarities are then measured on another kind of text."
            )
    return warnings


def gcp_status(settings: AppSettings) -> GcpKeyStatus:
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


def blank_page_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "DocuFlow connection check")
    try:
        return document.tobytes()
    finally:
        document.close()


def rule_model(rule: SupplierRule) -> SupplierRuleModel:
    return SupplierRuleModel(**asdict(rule))


async def lab_extractor(settings: AppSettings, definition: PipelineDefinition):
    from app.services.document_ai import DocumentAiClient
    from app.services.extraction_engine import resolve_extractor
    engines = []
    for step in definition.steps:
        if step.kind.value == "document_ai_extract":
            processor = str(step.config.get("processor_id") or settings.gcp.custom_extractor_processor_id)
            client = DocumentAiClient(GCP_CREDENTIALS_PATH, step.config.get("project_id") or settings.gcp.project_id, step.config.get("location") or settings.gcp.location)
            engines.append(await resolve_extractor(client, processor))
    return {**engines[0], "additional_processors": engines[1:]} if engines else None
