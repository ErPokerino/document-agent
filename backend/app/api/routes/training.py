"""Models: what is learned from the datasets, the readings it learns from, and where else it could be trained."""

import asyncio
import hashlib
import json
import re
from datetime import date
from typing import Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from app.api import deps
from app.domain.models import (
    AlgorithmInfo,
    ArtifactSummary,
    FineTuningExportRequest,
    TrainingRequest,
    ReadingCacheStatus,
    TrainingJobModel,
    TrainingProvider,
)
from app.pipeline.compiler import PipelineError
from app.pipeline.store import InvalidPipelineName, UnknownPipeline
from app.services.spreadsheet import content_disposition
from app.training.artifacts import InvalidArtifact, StoredArtifact, UnknownArtifact
from app.training.corpus import LabelledDocument, executable_readers, read_corpus, reader_signature, reading_steps
from app.training.jobs import TrainingJob
from app.training.algorithms import ALGORITHMS, algorithm as find_algorithm
from app.training.trainer import progress_callback, select_documents, train_model

router = APIRouter()

# Named so the section can show where training will go, without pretending any
# of it is wired. Each becomes "available" when DocuFlow can reach it.
PROVIDERS = [
    TrainingProvider(
        id="vertex_gemini_sft",
        name="Gemini supervised fine-tuning",
        platform="Google Cloud Vertex AI",
        trains="A tuned Gemini model served from a Vertex AI endpoint",
        status="not_connected",
        description=(
            "Tuning is offered on Vertex AI, not through the Gemini API key used in LLM. "
            "It needs a Vertex-enabled project, a Cloud Storage bucket for the training "
            "examples and a service account allowed to run tuning jobs. A tuned model "
            "depends on its base model and stops answering when that model is retired."
        ),
    ),
    TrainingProvider(
        id="document_ai_custom",
        name="Document AI custom processors",
        platform="Google Cloud Document AI",
        trains="A Custom Extractor version or a Custom Classifier",
        status="not_connected",
        description=(
            "Document AI trains extractor and classifier versions on labelled documents. "
            "A trained version can already be used here: register it in Processors and "
            "pin its version in a pipeline step."
        ),
    ),
    TrainingProvider(
        id="aws_bedrock",
        name="Bedrock model customization",
        platform="Amazon Web Services",
        trains="A fine-tuned foundation model",
        status="not_connected",
        description="Not connected. Listed as a target for when DocuFlow runs against AWS.",
    ),
    TrainingProvider(
        id="azure_openai",
        name="Azure OpenAI fine-tuning",
        platform="Microsoft Azure",
        trains="A fine-tuned deployment",
        status="not_connected",
        description="Not connected. Listed as a target for when DocuFlow runs against Azure.",
    ),
]


# -- reading cache -----------------------------------------------------------------


@router.get("/api/reading-cache", response_model=ReadingCacheStatus)
async def reading_cache_status() -> ReadingCacheStatus:
    stats = deps.reading_cache.stats()
    return ReadingCacheStatus(entries=stats.entries, size_bytes=stats.size_bytes)


@router.delete("/api/reading-cache", status_code=204, response_class=Response)
async def clear_reading_cache() -> Response:
    deps.reading_cache.clear()
    return Response(status_code=204)


# -- the registry --------------------------------------------------------------------


def _used_by(artifact: str) -> list[str]:
    return [
        definition.name
        for definition in deps.pipeline_store.list()
        if any(step.kind.value == "artifact_predict" and step.config.get("artifact_id") == artifact for step in definition.steps)
    ]


def _features_summary(text: dict[str, Any]) -> str:
    if not text:
        return ""
    unit = "character" if text.get("analyzer") == "char_wb" else "word"
    summary = f"TF-IDF, {unit} {text.get('ngram_min')}–{text.get('ngram_max')}-grams"
    if text.get("reduce_to"):
        summary += f", reduced to {text['reduce_to']} dimensions"
    return summary


def _summary(stored: StoredArtifact) -> ArtifactSummary:
    manifest = stored.manifest
    training = manifest.get("training") or {}
    validation = manifest.get("validation") or {}
    identity = str(manifest.get("algorithm") or "knn_tfidf")
    known = ALGORITHMS.get(identity)
    text = manifest.get("text") or manifest.get("parameters") or {}
    return ArtifactSummary(
        id=stored.id,
        name=str(manifest.get("name") or stored.id),
        kind=str(manifest.get("kind")),
        algorithm=identity,
        algorithm_label=known.label if known else identity,
        family=known.family if known else None,
        input_fields=list(manifest.get("input_fields") or []),
        features=_features_summary(text),
        hyperparameters={key: value for key, value in (manifest.get("parameters") or {}).items() if key in {spec.name for spec in (known.parameters if known else [])}},
        runnable=known is not None and known.status() == "available",
        created_at=str(manifest.get("created_at") or ""),
        entities=list(manifest.get("entities") or []),
        input=str(manifest.get("input") or "text"),
        parameters=dict(manifest.get("parameters") or {}),
        libraries=dict(manifest.get("libraries") or {}),
        datasets=list(training.get("datasets") or []),
        pipeline=training.get("pipeline"),
        reader=[str(entry.get("kind")) for entry in training.get("reader") or []],
        documents=len(training.get("documents") or []),
        cutoff_entity=training.get("cutoff_entity"),
        cutoff_before=training.get("cutoff_before"),
        excluded_by_cutoff=int(training.get("excluded_by_cutoff") or 0),
        unreadable=int(training.get("unreadable") or 0),
        validation_method=validation.get("method"),
        validation=validation.get("entities") or {},
        imported=bool(manifest.get("imported")),
        size_bytes=stored.size_bytes,
        used_by=_used_by(stored.id),
    )


@router.get("/api/artifacts", response_model=list[ArtifactSummary])
async def list_artifacts() -> list[ArtifactSummary]:
    return [_summary(stored) for stored in deps.artifact_store.list()]


@router.get("/api/artifacts/{artifact}", response_model=ArtifactSummary)
async def get_artifact(artifact: str) -> ArtifactSummary:
    try:
        return _summary(deps.artifact_store.get(artifact))
    except (UnknownArtifact, InvalidArtifact) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/artifacts/{artifact}", status_code=204, response_class=Response)
async def delete_artifact(artifact: str) -> Response:
    try:
        stored = deps.artifact_store.get(artifact)
    except (UnknownArtifact, InvalidArtifact) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    users = _used_by(artifact)
    if users:
        raise HTTPException(
            status_code=409,
            detail=f"'{stored.manifest.get('name') or artifact}' is used by the pipeline{'s' if len(users) > 1 else ''} {', '.join(users)}.",
        )
    deps.artifact_store.delete(artifact)
    return Response(status_code=204)


@router.get("/api/artifacts/{artifact}/export.zip", response_class=Response)
async def export_artifact(artifact: str) -> Response:
    try:
        stored = deps.artifact_store.get(artifact)
        content = deps.artifact_store.export(artifact)
    except (UnknownArtifact, InvalidArtifact) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filename = f"{stored.manifest.get('name') or 'model'}-{artifact[:8]}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition("attachment", filename)},
    )


@router.post("/api/artifacts/import", response_model=ArtifactSummary, status_code=201)
async def import_artifact(file: UploadFile = File(...)) -> ArtifactSummary:
    content = await file.read()
    try:
        stored = await asyncio.to_thread(deps.artifact_store.import_archive, content)
    except InvalidArtifact as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _summary(stored)


# -- training ----------------------------------------------------------------------


@router.get("/api/training/providers", response_model=list[TrainingProvider])
async def training_providers() -> list[TrainingProvider]:
    return PROVIDERS


def _job_model(job: TrainingJob) -> TrainingJobModel:
    return TrainingJobModel(
        id=job.id, kind=job.kind, name=job.name, created_at=job.created_at, status=job.status,  # type: ignore[arg-type]
        total=job.total, done=job.done, artifact_id=job.artifact_id, error=job.error, skipped=job.skipped,
        output=job.output, examples=job.examples, phase=job.phase,
    )


@router.get("/api/training/jobs", response_model=list[TrainingJobModel])
async def list_training_jobs() -> list[TrainingJobModel]:
    return [_job_model(job) for job in deps.training_jobs.all()]


@router.post("/api/training/jobs/{job_id}/cancel", response_model=TrainingJobModel, status_code=202)
async def cancel_training_job(job_id: int) -> TrainingJobModel:
    job = deps.training_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No training job with id {job_id}")
    if job.status != "running":
        raise HTTPException(status_code=409, detail="That training job is not running.")
    job.cancelled.set()
    if job.task is not None and not job.task.done():
        job.task.cancel()
    job.status = "cancelled"
    return _job_model(job)


def _labelled_documents(datasets: list[str]) -> list[LabelledDocument]:
    documents = []
    for dataset in datasets:
        for summary in deps.dataset_store.list_documents(dataset):
            if not summary.labelled:
                continue
            label_file = deps.dataset_store.read_labels(dataset, summary.name)
            if label_file is None:
                continue
            content = deps.dataset_store.read_document(dataset, summary.name)
            documents.append(
                LabelledDocument(
                    dataset=dataset,
                    name=summary.name,
                    sha256=hashlib.sha256(content).hexdigest(),
                    content=content,
                    labels=label_file.labels,
                )
            )
    return documents


@router.get("/api/training/algorithms", response_model=list[AlgorithmInfo])
async def training_algorithms() -> list[AlgorithmInfo]:
    return [algorithm.info() for algorithm in ALGORITHMS.values()]


@router.post("/api/training/models", response_model=TrainingJobModel, status_code=202)
async def start_training(request: TrainingRequest) -> TrainingJobModel:
    if deps.training_jobs.running() is not None:
        raise HTTPException(status_code=409, detail="A training job is already running.")
    try:
        chosen = find_algorithm(request.algorithm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if chosen.status() == "not_connected":
        raise HTTPException(status_code=400, detail=f"{chosen.label} runs on a service DocuFlow is not connected to.")
    if chosen.status() == "not_installed":
        raise HTTPException(status_code=400, detail=f"{chosen.label} is not installed on this machine: {chosen.install}.")
    try:
        parameters = chosen.resolve(request.parameters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for dataset in request.datasets:
        deps.require_dataset(dataset)
    settings = deps.settings_store.read()
    configured = {entity.name: entity for entity in settings.prompts.entities}
    unknown = [name for name in [*request.entities, *request.input_fields] if name not in configured]
    if unknown:
        raise HTTPException(status_code=400, detail=f"These fields are not configured in Extraction: {', '.join(unknown)}")
    if request.input_fields and not chosen.takes_fields:
        raise HTTPException(status_code=400, detail=f"{chosen.label} reads the text alone; it takes no fields as input.")
    both = sorted(set(request.entities) & set(request.input_fields))
    if both:
        raise HTTPException(status_code=400, detail=f"A field cannot be both predicted and read as input: {', '.join(both)}")
    cutoff: date | None = None
    if request.cutoff_before:
        if not request.cutoff_entity or request.cutoff_entity not in configured:
            raise HTTPException(status_code=400, detail="A cutoff needs the date field it is read from.")
        try:
            cutoff = date.fromisoformat(request.cutoff_before)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="The cutoff is not a YYYY-MM-DD date.") from exc

    definition, readers = _reading_plan(request.pipeline, settings)
    await _pin_reader_versions(readers, settings)

    documents = await asyncio.to_thread(_labelled_documents, request.datasets)
    selected, excluded = select_documents(documents, request.entities, request.cutoff_entity if cutoff else None, cutoff)
    if len(selected) < 2:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(selected)} labelled document{'' if len(selected) == 1 else 's'} for these fields"
                + (f" dated before {request.cutoff_before}" if cutoff else "")
                + ". At least two are needed to train."
            ),
        )

    job = deps.training_jobs.start(chosen.id, request.name)
    job.total = len(selected)
    job.phase = "reading"
    steps = executable_readers(readers, definition.page_limit)
    targets = [configured[name] for name in request.entities]
    inputs = [configured[name] for name in request.input_fields]
    training: dict[str, Any] = {
        "datasets": request.datasets,
        "pipeline": definition.name,
        "page_limit": definition.page_limit,
        "reader": reader_signature(readers),
        "cutoff_entity": request.cutoff_entity if cutoff else None,
        "cutoff_before": request.cutoff_before if cutoff else None,
        "excluded_by_cutoff": excluded,
    }

    def on_phase(phase: str) -> None:
        job.phase = phase

    async def drive() -> None:
        try:
            read, skipped = await read_corpus(
                selected,
                steps,
                # Training measures nothing about time or cost: stored readings
                # are always reused.
                lambda name, content: deps.pipeline_context(settings, name, content, reuse_readings=True),
                on_progress=progress_callback(job),
                cancelled=job.cancelled,
            )
            job.skipped = [f"{name}: {reason}" for name, reason in skipped]
            if len(read) < 2:
                raise ValueError(f"Text was read from {len(read)} of {len(selected)} documents; at least two are needed.")
            stored = await asyncio.to_thread(
                train_model,
                store=deps.artifact_store,
                name=request.name,
                algorithm=chosen,
                read=read,
                targets=targets,
                input_fields=inputs,
                text=request.text,
                parameters=parameters,
                training={**training, "unreadable": len(skipped)},
                on_phase=on_phase,
            )
            job.artifact_id = stored.id
            job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
        except Exception as exc:  # noqa: BLE001 - a job must never end silently
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.phase = None

    job.task = asyncio.create_task(drive())
    return _job_model(job)


def _reading_plan(pipeline: str, settings: Any) -> tuple[Any, list[Any]]:
    """The pipeline, and the reading steps a corpus is read with."""
    from app.services.processors import resolved_pipeline

    try:
        definition = resolved_pipeline(deps.pipeline_store.read(pipeline), settings.gcp)
        return definition, reading_steps(definition)
    except (UnknownPipeline, InvalidPipelineName) as exc:
        raise HTTPException(status_code=404, detail=f"No pipeline named {pipeline}") from exc
    except (PipelineError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/training/exports", response_model=TrainingJobModel, status_code=202)
async def start_fine_tuning_export(request: FineTuningExportRequest) -> TrainingJobModel:
    """Write the labelled datasets as supervised fine-tuning examples, one JSON per line."""
    from app.training.sft import example

    if deps.training_jobs.running() is not None:
        raise HTTPException(status_code=409, detail="A training job is already running.")
    for dataset in request.datasets:
        deps.require_dataset(dataset)
    settings = deps.settings_store.read()
    definition, readers = _reading_plan(request.pipeline, settings)
    await _pin_reader_versions(readers, settings)
    documents = await asyncio.to_thread(_labelled_documents, request.datasets)
    if not documents:
        raise HTTPException(status_code=400, detail="These datasets hold no labelled document.")

    job = deps.training_jobs.start("fine_tuning_export", request.name)
    job.total = len(documents)
    steps = executable_readers(readers, definition.page_limit)
    prompts = settings.prompts

    async def drive() -> None:
        try:
            read, skipped = await read_corpus(
                documents,
                steps,
                lambda name, content: deps.pipeline_context(settings, name, content, reuse_readings=True),
                on_progress=progress_callback(job),
                cancelled=job.cancelled,
            )
            lines = []
            for item in read:
                try:
                    lines.append(json.dumps(
                        example(request.format, prompts, item.document.labels, item.text,
                                total_pages=item.total_pages, processed_pages=item.processed_pages),
                        ensure_ascii=False,
                    ))
                except ValueError as exc:
                    skipped.append((f"{item.document.dataset}/{item.document.name}", str(exc)))
            job.skipped = [f"{name}: {reason}" for name, reason in skipped]
            if not lines:
                raise ValueError("No document could be written as an example.")
            deps.EXPORTS_PATH.mkdir(parents=True, exist_ok=True)
            output = f"{job.id}-{safe_file_name(request.name)}-{request.format}.jsonl"
            (deps.EXPORTS_PATH / output).write_text("\n".join(lines) + "\n", encoding="utf-8")
            job.output = output
            job.examples = len(lines)
            job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
        except Exception as exc:  # noqa: BLE001 - a job must never end silently
            job.status = "failed"
            job.error = str(exc)

    job.task = asyncio.create_task(drive())
    return _job_model(job)


@router.get("/api/training/exports/{output}", response_class=Response)
async def download_fine_tuning_export(output: str) -> Response:
    if not re.fullmatch(r"[0-9]+-[A-Za-z0-9._-]+\.jsonl", output):
        raise HTTPException(status_code=404, detail="No such export")
    path = deps.EXPORTS_PATH / output
    if not path.exists():
        raise HTTPException(status_code=404, detail="No such export")
    return Response(
        content=path.read_bytes(),
        media_type="application/jsonl",
        headers={"Content-Disposition": content_disposition("attachment", output)},
    )


def safe_file_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:60] or "export"


async def _pin_reader_versions(readers: list[Any], settings: Any) -> None:
    """Read each Document AI processor at one version, as a Lab run does.

    A pinned version is also what lets the readings be stored and reused.
    """
    from app.services.document_ai import DocumentAiClient
    from app.services.extraction_engine import resolve_extractor

    for step in readers:
        if step.kind.value not in ("document_ai_ocr", "document_ai_layout"):
            continue
        config = step.config
        if "/processorVersions/" in str(config.get("processor_id") or ""):
            continue
        client = DocumentAiClient(
            deps.GCP_CREDENTIALS_PATH,
            config.get("project_id") or settings.gcp.project_id,
            config.get("location") or settings.gcp.location,
        )
        identity = await resolve_extractor(client, str(config.get("processor_id") or ""))
        if identity["version"]:
            config["processor_id"] = identity["processor_id"] + "/processorVersions/" + identity["version"]
