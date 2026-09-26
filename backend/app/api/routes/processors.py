"""The Document AI resource catalog."""

from fastapi import HTTPException, Response, APIRouter

from app.api import deps
from app.domain.models import (
    AppSettings,
    DocumentProcessor,
    ProcessorRecord,
    ProcessorInspection,
    ProcessorVersion,
)
from app.services.document_ai import DocumentAiClient, DocumentAiError
from app.services.processors import used_by as processor_used_by

router = APIRouter()


@router.get("/api/processors", response_model=list[ProcessorRecord])
async def list_processors():
    settings = deps.settings_store.read()
    pipelines = deps.pipeline_store.list()
    return [ProcessorRecord(**entry.model_dump(), used_by=processor_used_by(entry, pipelines, settings.gcp)) for entry in settings.gcp.processors]


@router.put("/api/processors/{processor_ref}", response_model=DocumentProcessor)
async def save_processor(processor_ref: str, entry: DocumentProcessor):
    if processor_ref != entry.id:
        raise HTTPException(status_code=400, detail="The processor reference does not match its id")
    entry.name = entry.name.strip()
    if not entry.name:
        raise HTTPException(status_code=400, detail="A processor name is required")

    def registered(settings: AppSettings) -> AppSettings:
        existing = next((p for p in settings.gcp.processors if p.id == entry.id), None)
        identity_fields = ("kind", "project_id", "location", "processor_id")
        if existing and any(getattr(existing, f) != getattr(entry, f) for f in identity_fields):
            raise HTTPException(status_code=409, detail="A registered processor's identity cannot change. Register another processor to use a different resource.")
        if any(p.id != entry.id and all(getattr(p, f) == getattr(entry, f) for f in identity_fields) for p in settings.gcp.processors):
            raise HTTPException(status_code=409, detail="This processor is already registered")
        settings.gcp.processors = [p for p in settings.gcp.processors if p.id != entry.id] + [entry]
        return settings

    deps.settings_store.update(registered)
    return entry


@router.delete("/api/processors/{processor_ref}", status_code=204, response_class=Response)
async def delete_processor(processor_ref: str):
    from app.services.processors import KINDS
    pipelines = deps.pipeline_store.list()

    def removed(settings: AppSettings) -> AppSettings:
        entry = next((p for p in settings.gcp.processors if p.id == processor_ref), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="Processor not found")
        names = processor_used_by(entry, pipelines, settings.gcp)
        if names:
            raise HTTPException(status_code=409, detail="Processor used by: " + ", ".join(names))
        settings.gcp.processors = [p for p in settings.gcp.processors if p.id != processor_ref]
        field = KINDS[entry.kind]
        if (settings.gcp.project_id, settings.gcp.location, getattr(settings.gcp, field).split("/processorVersions/")[0]) == (entry.project_id, entry.location, entry.processor_id):
            setattr(settings.gcp, field, "")
        return settings

    deps.settings_store.update(removed)
    return Response(status_code=204)


@router.get("/api/processors/{processor_ref}/inspect", response_model=ProcessorInspection)
async def inspect_processor(processor_ref: str):
    from datetime import datetime, timezone
    settings = deps.settings_store.read()
    entry = next((p for p in settings.gcp.processors if p.id == processor_ref), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Processor not found")
    client = DocumentAiClient(deps.GCP_CREDENTIALS_PATH, entry.project_id, entry.location)
    resource = f"projects/{entry.project_id}/locations/{entry.location}/processors/{entry.processor_id}"
    expected = {"document_ai_ocr": "OCR_PROCESSOR", "document_ai_layout": "LAYOUT_PARSER_PROCESSOR", "document_ai_extract": "CUSTOM_EXTRACTION_PROCESSOR"}
    try:
        metadata = await client.metadata(resource)
        if metadata.get("type") != expected[entry.kind]:
            raise HTTPException(status_code=409, detail="Google reports a different processor type from the registered type")
        versions = []
        token = None
        seen = set()
        while True:
            page = await client.metadata(resource + "/processorVersions", page_token=token)
            versions.extend(ProcessorVersion(id=v["name"].rsplit("/", 1)[-1], name=v.get("displayName") or v["name"].rsplit("/", 1)[-1], state=v.get("state") or "UNKNOWN") for v in page.get("processorVersions", []))
            token = page.get("nextPageToken")
            if not token:
                break
            if token in seen:
                raise DocumentAiError("The processor version cursor did not advance")
            seen.add(token)
        return ProcessorInspection(display_name=metadata.get("displayName") or entry.name, state=metadata.get("state") or "UNKNOWN", default_version=(metadata.get("defaultProcessorVersion") or "").rsplit("/", 1)[-1] or None, versions=versions, checked_at=datetime.now(timezone.utc).isoformat())
    except DocumentAiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
