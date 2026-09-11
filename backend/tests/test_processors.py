"""Catalog changes cannot silently retarget a pipeline or a saved experiment."""
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app import main
from app.domain.models import AppSettings, DocumentProcessor, GcpSettings, PromptConfiguration
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
from app.pipeline.compiler import build_steps
from app.pipeline.store import PipelineStore
from app.services.processors import binding, migrate_processor_catalog, resolved_pipeline
from app.services.settings_store import SettingsStore
from app.services.document_ai import DocumentAiClient


def resource(**overrides):
    return DocumentProcessor(**(dict(id="ocr", name="Invoices OCR", kind="document_ai_ocr", project_id="other-project", location="us", processor_id="abc") | overrides))


def pipeline(config):
    return PipelineDefinition(name="OCR", steps=[PipelineStep(kind=StepKind.document_ai_ocr, config=config), PipelineStep(kind=StepKind.llm_extract)])


def test_a_step_uses_its_registered_project_region_and_explicit_version():
    """Global defaults cannot override an explicit per-step resource."""
    gcp = GcpSettings(project_id="global", location="eu", processors=[resource()])
    steps = build_steps(pipeline({"processor_ref": "ocr", "processor_version": "v2"}), prompts=PromptConfiguration(), entities=[], gcp=gcp)
    assert (steps[1].project_id, steps[1].location, steps[1].processor_id) == ("other-project", "us", "abc/processorVersions/v2")


@pytest.mark.parametrize("config", [{"processor_ref": "missing"}, {"processor_ref": "ocr", "processor_version": "v1?query"}])
def test_invalid_references_and_versions_are_rejected(config):
    """A missing resource must never fall back to a different processor."""
    with pytest.raises(ValueError):
        binding(pipeline(config).steps[0], GcpSettings(processors=[resource()]))


def test_incompatible_processor_types_are_rejected():
    """A Custom Extractor is not an OCR processor."""
    with pytest.raises(ValueError, match="type"):
        binding(pipeline({"processor_ref": "ocr"}).steps[0], GcpSettings(processors=[resource(kind="document_ai_extract")]))


def test_resolved_snapshots_do_not_depend_on_the_catalog():
    """A retry still resolves after a catalog entry is removed."""
    frozen = resolved_pipeline(pipeline({"processor_ref": "ocr", "processor_version": "v2"}), GcpSettings(processors=[resource()]))
    assert "processor_ref" not in frozen.steps[0].config
    again = resolved_pipeline(frozen, GcpSettings(project_id="changed", location="eu"))
    assert again == frozen


def test_migration_preserves_overrides_versions_and_is_idempotent(tmp_path):
    """Importing old defaults and step overrides must preserve the executed resource."""
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(gcp=GcpSettings(project_id="original", ocr_processor_id="default")))
    store = PipelineStore(tmp_path / "pipelines")
    original = pipeline({"processor_id": "override/processorVersions/v4", "feeds_model": False})
    store.save(original)
    expected = resolved_pipeline(original, settings.read().gcp)
    migrate_processor_catalog(settings, store)
    migrated = store.read("OCR")
    assert migrated.steps[0].config["processor_version"] == "v4"
    assert resolved_pipeline(migrated, settings.read().gcp) == expected
    before = settings.path.read_bytes()
    migrate_processor_catalog(settings, store)
    assert settings.path.read_bytes() == before
    assert settings.path.with_suffix(".pre-processors.bak").exists()
    assert (store.root / "OCR.pre-processors.bak").exists()


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(gcp=GcpSettings(processors=[resource()])))
    monkeypatch.setattr(main, "settings_store", settings)
    return settings


@pytest.mark.asyncio
async def test_a_processor_used_in_a_saved_pipeline_cannot_be_removed(catalog):
    """Catalog deletion must not leave dangling pipeline references."""
    main.pipeline_store.save(pipeline({"processor_ref": "ocr"}))
    with pytest.raises(HTTPException) as exc:
        await main.delete_processor("ocr")
    assert exc.value.status_code == 409
    assert len(catalog.read().gcp.processors) == 1


@pytest.mark.asyncio
async def test_renaming_keeps_identity_and_changing_identity_is_refused(catalog):
    """Editing a catalog label must not silently retarget every pipeline using it."""
    await main.save_processor("ocr", resource(name="Better name"))
    assert catalog.read().gcp.processors[0].name == "Better name"
    with pytest.raises(HTTPException) as exc:
        await main.save_processor("ocr", resource(processor_id="changed"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_resources_are_rejected(catalog):
    """Multiple labels for the same resource make version selection ambiguous."""
    with pytest.raises(HTTPException) as exc:
        await main.save_processor("another", resource(id="another"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_inspection_reads_all_version_pages_without_processing_documents(catalog, monkeypatch):
    """Version discovery is metadata-only and must not hide later result pages."""
    mock = AsyncMock(side_effect=[{"type": "OCR_PROCESSOR", "state": "ENABLED", "defaultProcessorVersion": "path/v2"}, {"processorVersions": [{"name": "path/v1", "state": "DEPLOYED"}], "nextPageToken": "next"}, {"processorVersions": [{"name": "path/v2", "state": "DEPLOYED"}]}])
    monkeypatch.setattr(DocumentAiClient, "metadata", mock)
    process = AsyncMock(side_effect=AssertionError("must not process"))
    monkeypatch.setattr(DocumentAiClient, "process", process)
    result = await main.inspect_processor("ocr")
    assert [v.id for v in result.versions] == ["v1", "v2"]
    assert result.default_version == "v2"
    process.assert_not_called()


@pytest.mark.asyncio
async def test_inspection_rejects_a_mismatched_google_type(catalog, monkeypatch):
    """A mistyped registration must be reported before it is trusted."""
    monkeypatch.setattr(DocumentAiClient, "metadata", AsyncMock(return_value={"type": "CUSTOM_EXTRACTION_PROCESSOR"}))
    with pytest.raises(HTTPException) as exc:
        await main.inspect_processor("ocr")
    assert exc.value.status_code == 409


def test_a_new_step_requires_an_explicit_catalog_choice():
    """New steps must not silently inherit the obsolete global processor slot."""
    with pytest.raises(ValueError, match="Select a processor"):
        binding(pipeline({"processor_ref": ""}).steps[0], GcpSettings(ocr_processor_id="legacy"))


@pytest.mark.parametrize("version", [
    "pretrained-foundation-model-v3.1-lite-2026-07-15",
    "pretrained-foundation-model-v1.5.1-2025-08-07",
    "pretrained-ocr-v2.1-2024-08-07",
])
def test_google_versions_with_decimal_components_compile_unchanged(version):
    """Google's real version IDs contain periods, unlike the original v2 fixture."""
    entry = resource(kind="document_ai_extract")
    definition = PipelineDefinition(name="CE", steps=[PipelineStep(kind=StepKind.document_ai_extract, config={"processor_ref": entry.id, "processor_version": version})])
    steps = build_steps(definition, prompts=PromptConfiguration(), entities=[], gcp=GcpSettings(processors=[entry]))
    assert steps[1].processor_id == f"abc/processorVersions/{version}"


@pytest.mark.parametrize("version", ["..", "../v1", "v1/path", "v1?query", "v1#fragment", "v1%2Fpath", "v1 version"])
def test_version_validation_rejects_path_and_url_syntax(version):
    """Allowing dotted version names must not admit URL or path changes."""
    with pytest.raises(ValueError, match="Invalid processor version"):
        binding(pipeline({"processor_ref": "ocr", "processor_version": version}).steps[0], GcpSettings(processors=[resource()]))
