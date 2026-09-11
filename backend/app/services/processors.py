"""Resolve catalog references into concrete bindings before execution or snapshots."""
import hashlib
import re
from app.domain.models import GcpSettings
from app.pipeline.definition import PipelineDefinition, PipelineStep

KINDS = {"document_ai_ocr": "ocr_processor_id", "document_ai_layout": "layout_processor_id", "document_ai_extract": "custom_extractor_processor_id"}
LABELS = {"document_ai_ocr": "OCR", "document_ai_layout": "Layout Parser", "document_ai_extract": "Custom Extractor"}


def legacy_catalog(gcp: dict) -> list[dict]:
    entries = []
    for kind, field in KINDS.items():
        processor = str(gcp.get(field) or "").split("/processorVersions/")[0]
        project = gcp.get("project_id") or ""
        if not processor or not project:
            continue
        location = gcp.get("location") or "eu"
        identity = f"{kind}/{project}/{location}/{processor}"
        from app.domain.models import DocumentProcessor
        from pydantic import ValidationError
        try:
            entry = DocumentProcessor(id="imported-" + hashlib.sha256(identity.encode()).hexdigest()[:16], name=LABELS[kind], kind=kind, project_id=project, location=location, processor_id=processor)
        except ValidationError:
            continue
        entries.append(entry.model_dump())
    return entries


def binding(step: PipelineStep, gcp: GcpSettings) -> dict:
    config = dict(step.config)
    ref = config.get("processor_ref")
    if "processor_ref" in config and not ref:
        raise ValueError("Select a processor for this pipeline step")
    if ref:
        entry = next((p for p in gcp.processors if p.id == ref), None)
        if entry is None:
            raise ValueError("The selected processor is no longer in Processors")
        if entry.kind != step.kind.value:
            raise ValueError("The selected processor type does not match this step")
        version = str(config.get("processor_version") or "")
        if version and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", version):
            raise ValueError("Invalid processor version")
        config.update(project_id=entry.project_id, location=entry.location, processor_id=entry.processor_id + ("/processorVersions/" + version if version else ""))
        config.pop("processor_ref", None)
        config.pop("processor_version", None)
    else:
        config.setdefault("project_id", gcp.project_id)
        config.setdefault("location", gcp.location)
        config["processor_id"] = config.get("processor_id") or getattr(gcp, KINDS[step.kind.value])
    return config


def resolved_pipeline(definition: PipelineDefinition, gcp: GcpSettings) -> PipelineDefinition:
    result = definition.model_copy(deep=True)
    for step in result.steps:
        if step.kind.value in KINDS:
            step.config = binding(step, gcp)
    return result


def used_by(entry, pipelines, gcp) -> list[str]:
    names = []
    for pipeline in pipelines:
        for step in pipeline.steps:
            if step.kind.value != entry.kind:
                continue
            if step.config.get("processor_ref") == entry.id:
                names.append(pipeline.name)
                break
            if step.config.get("processor_ref"):
                continue
            config = binding(step, gcp)
            if (config["project_id"], config["location"], str(config["processor_id"]).split("/processorVersions/")[0]) == (entry.project_id, entry.location, entry.processor_id):
                names.append(pipeline.name)
                break
    return names


def migrate_processor_catalog(settings_store, pipeline_store) -> None:
    """Persist imported resources before rewriting references; interrupted migration can resume."""
    from app.domain.models import DocumentProcessor
    from pydantic import ValidationError
    settings = settings_store.read()
    catalog = list(settings.gcp.processors)
    updates = []
    for pipeline in pipeline_store.list():
        changed = False
        for step in pipeline.steps:
            if step.kind.value not in KINDS or step.config.get("processor_ref"):
                continue
            try:
                config = binding(step, settings.gcp)
            except ValueError:
                continue
            processor, _, version = str(config["processor_id"]).partition("/processorVersions/")
            identity = f"{step.kind.value}/{config['project_id']}/{config['location']}/{processor}"
            try:
                entry = DocumentProcessor(id="imported-" + hashlib.sha256(identity.encode()).hexdigest()[:16], name=LABELS[step.kind.value], kind=step.kind.value, project_id=config["project_id"], location=config["location"], processor_id=processor)
            except ValidationError:
                continue
            existing = next((p for p in catalog if (p.kind, p.project_id, p.location, p.processor_id) == (entry.kind, entry.project_id, entry.location, entry.processor_id)), None)
            if existing:
                entry = existing
            else:
                catalog.append(entry)
            step.config = {key: value for key, value in step.config.items() if key not in ("project_id", "location", "processor_id")}
            step.config.update(processor_ref=entry.id, processor_version=version)
            changed = True
        if changed:
            updates.append(pipeline)
    if not updates:
        return
    if settings_store.path.exists():
        backup = settings_store.path.with_suffix(".pre-processors.bak")
        if not backup.exists():
            backup.write_bytes(settings_store.path.read_bytes())
    settings.gcp.processors = catalog
    settings_store.write(settings)
    for pipeline in updates:
        path = pipeline_store.root / (pipeline.name + ".json")
        if path.exists():
            backup = path.with_suffix(".pre-processors.bak")
            if not backup.exists():
                backup.write_bytes(path.read_bytes())
        pipeline_store.save(pipeline)
