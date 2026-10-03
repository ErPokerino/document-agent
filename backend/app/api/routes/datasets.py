"""Datasets and their ground truth."""

import time
from dataclasses import asdict

from fastapi import File, Form, HTTPException, Response, UploadFile, APIRouter

from app.api import deps
from app.domain.models import (
    Dataset,
    DatasetCreateRequest,
    DatasetDocument,
    DocumentLabels,
    DraftLabels,
    EntityFormat,
    LabelsRequest,
    LabelValue,
    PromoteRunRequest,
)
from app.evaluation.dataset_archive import ArchiveError, read_archive, write_archive
from app.evaluation.datasets import DuplicateDocument, InvalidName
from app.services.field_validation import canonical_category
from app.services.spreadsheet import content_disposition

router = APIRouter()


@router.get("/api/datasets", response_model=list[Dataset])
async def list_datasets() -> list[Dataset]:
    return [Dataset(**asdict(dataset)) for dataset in deps.dataset_store.list_datasets()]


@router.post("/api/datasets", response_model=Dataset, status_code=201)
async def create_dataset(request: DatasetCreateRequest) -> Dataset:
    try:
        return Dataset(**asdict(deps.dataset_store.create(request.name)))
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/api/datasets/{name}", response_model=Dataset)
async def rename_dataset(name: str, request: DatasetCreateRequest) -> Dataset:
    try:
        return Dataset(**asdict(deps.dataset_store.rename(name, request.name)))
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/datasets/{name}", status_code=204, response_class=Response)
async def delete_dataset(name: str) -> Response:
    try:
        deps.dataset_store.delete(name)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/api/label-values/{entity}", response_model=list[LabelValue])
async def label_values(entity: str) -> list[LabelValue]:
    """The values labelled for one field across every dataset: an open category's classes."""
    return [LabelValue(value=value, documents=count) for value, count in deps.dataset_store.label_values(entity)]


@router.get("/api/datasets/{name}/documents", response_model=list[DatasetDocument])
async def list_dataset_documents(name: str) -> list[DatasetDocument]:
    deps.require_dataset(name)
    return [DatasetDocument(**asdict(document)) for document in deps.dataset_store.list_documents(name)]


@router.get("/api/datasets/{name}/export.zip", response_class=Response)
async def export_dataset(name: str) -> Response:
    """The whole dataset as one file: the PDFs, their ground truth, a manifest."""
    deps.require_dataset(name)
    try:
        archive = write_archive(deps.dataset_store, name)
    except ArchiveError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition("attachment", f"{name}.zip")},
    )


@router.post("/api/datasets/import", response_model=Dataset, status_code=201)
async def import_dataset(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> Dataset:
    """Create a dataset from an archive someone else exported.

    `name` overrides what the archive calls itself, which is how the same
    archive can be imported twice under two names, and how an archive that
    carries no manifest gets one at all.
    """
    content = await file.read(deps.MAX_ARCHIVE_SIZE + 1)
    if len(content) > deps.MAX_ARCHIVE_SIZE:
        limit = deps.MAX_ARCHIVE_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=413, detail=f"The archive exceeds the {limit} MB limit"
        )
    try:
        summary = read_archive(deps.dataset_store, content, name=(name or "").strip() or None)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ArchiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Dataset(**asdict(summary))


@router.post("/api/datasets/{name}/documents", response_model=DatasetDocument, status_code=201)
async def add_dataset_document(name: str, file: UploadFile = File(...)) -> DatasetDocument:
    deps.require_dataset(name)
    content = await file.read(deps.MAX_FILE_SIZE + 1)
    if len(content) > deps.MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="The PDF exceeds the 20 MB limit")
    try:
        added = deps.dataset_store.add_document(name, file.filename or "document.pdf", content)
    except DuplicateDocument as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return DatasetDocument(**asdict(added))


@router.delete("/api/datasets/{name}/documents/{document}", status_code=204, response_class=Response)
async def delete_dataset_document(name: str, document: str) -> Response:
    deps.require_dataset(name)
    try:
        deps.dataset_store.remove_document(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/api/datasets/{name}/documents/{document}/file", response_class=Response)
async def read_dataset_document(name: str, document: str) -> Response:
    """Serve the PDF itself, so the reviewer can look at it while labelling."""
    deps.require_dataset(name)
    try:
        content = deps.dataset_store.read_document(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"No document named {document}") from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition("inline", document)},
    )


@router.get("/api/datasets/{name}/documents/{document}/labels", response_model=DocumentLabels)
async def get_document_labels(name: str, document: str) -> DocumentLabels:
    deps.require_dataset(name)
    try:
        label_file = deps.dataset_store.read_labels(name, document)
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


@router.put("/api/datasets/{name}/documents/{document}/labels", response_model=DocumentLabels)
async def set_document_labels(name: str, document: str, request: LabelsRequest) -> DocumentLabels:
    deps.require_dataset(name)
    entities = {entity.name: entity for entity in deps.settings_store.read().prompts.entities}
    unknown = sorted(set(request.labels) - set(entities))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="These labels name entities that are not configured: " + ", ".join(unknown),
        )
    labels = dict(request.labels)
    for key, value in request.labels.items():
        entity = entities[key]
        # A closed category's label is one of its classes, spelled as the
        # vocabulary spells it; a label outside it would be a class that no
        # reader is allowed to answer.
        if entity.format is EntityFormat.category and entity.categories and value is not None:
            try:
                labels[key] = canonical_category(value, entity)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"{value!r} is not a label for '{key}': {exc}.") from exc
    try:
        label_file = deps.dataset_store.set_labels(name, document, labels, source="manual")
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentLabels(
        document=document,
        source=label_file.source,
        labels=label_file.labels,
        updated_at=label_file.updated_at,
    )


@router.post("/api/datasets/{name}/documents/from-run", response_model=list[DatasetDocument], status_code=201)
async def promote_runs_to_dataset(name: str, request: PromoteRunRequest) -> list[DatasetDocument]:
    deps.require_dataset(name)

    # Resolve everything first: a batch that names a missing run fails before it
    # has half-populated the dataset.
    resolved = []
    filenames: set[str] = set()
    for run_id in request.run_ids:
        run = deps.run_store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
        content = deps.run_store.read_document(run.file_sha256)
        if content is None:
            raise HTTPException(
                status_code=410,
                detail=f"The original PDF for run {run_id} is no longer stored on this device.",
            )
        try:
            deps.dataset_store.check_new_document(name, run.filename)
            if run.filename.casefold() in filenames:
                raise DuplicateDocument(f"The selected runs contain the same document name: {run.filename!r}")
        except DuplicateDocument as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidName as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filenames.add(run.filename.casefold())
        resolved.append((run, content, deps.run_store.validated_values(run_id) or {}))

    added: list[DatasetDocument] = []
    for run, content, labels in resolved:
        try:
            document = deps.dataset_store.add_document(
                name, run.filename, content, labels=labels, source="promoted_run"
            )
        except InvalidName as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        added.append(DatasetDocument(**asdict(document)))
    return added


@router.post("/api/datasets/{name}/documents/{document}/draft-labels", response_model=DraftLabels)
async def draft_labels(name: str, document: str) -> DraftLabels:
    """Propose ground truth by running the active model. Nothing is saved.

    A blank labelling form for twenty invoices is why datasets never get built.
    A draft the reviewer corrects is the same work as reading the document once.
    """
    deps.require_dataset(name)
    settings = deps.settings_store.read()
    pipeline_definition = deps.selected_pipeline(settings)
    selected_model = await deps.ensure_model_ready(settings, pipeline_definition)
    execution_profile = deps.execution_profile(settings, pipeline_definition, selected_model)
    recorded_model, recorded_provider = deps.recorded_model(settings, pipeline_definition)

    try:
        content = deps.dataset_store.read_document(name, document)
    except InvalidName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"No document named {document}") from exc

    async with deps.exclusive_model_operation("processing"):
        context = deps.pipeline_context(settings, document, content)
        pipeline = deps.document_pipeline(settings)
        started = time.perf_counter()
        try:
            result = await pipeline.run(context)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        extraction = result.artifacts["extraction"]
        deps.run_store.record_run(
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
