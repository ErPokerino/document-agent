from unittest.mock import AsyncMock

import pytest

from app.services.document_ai import DocumentAiClient, DocumentAiError
from app.services.extraction_engine import resolve_extractor
from app.evaluation.store import EvaluationStore
from app.domain.models import PromptConfiguration


@pytest.mark.asyncio
async def test_default_version_and_base_model_are_resolved_from_metadata(tmp_path):
    """The label names the revision invoked, not just a mutable processor."""
    client = DocumentAiClient(tmp_path / "key", "project", "eu")
    client.metadata = AsyncMock(side_effect=[
        {"displayName": "Invoices", "defaultProcessorVersion": "projects/project/locations/eu/processors/p/processorVersions/v2"},
        {"genAiModelInfo": {"customGenAiModelInfo": {"baseProcessorVersionId": "foundation-v1"}}},
    ])
    result = await resolve_extractor(client, "p")
    assert result["version"] == "v2"
    assert result["base_model"] == "foundation-v1"
    assert result["display_name"] == "Invoices"


@pytest.mark.asyncio
async def test_numeric_project_names_and_aliases_resolve_to_concrete_versions(tmp_path):
    """Google responds with a project number even when requested by project id."""
    client = DocumentAiClient(tmp_path / "key", "project", "eu")
    canonical = "projects/123/locations/eu/processors/p"
    client.metadata = AsyncMock(side_effect=[
        {"name": canonical, "processorVersionAliases": [{"alias": canonical + "/processorVersions/stable", "processorVersion": canonical + "/processorVersions/v3"}]}, {},
    ])
    assert (await resolve_extractor(client, "p/processorVersions/stable"))["version"] == "v3"
    assert client.metadata.call_args.args[0] == "projects/project/locations/eu/processors/p/processorVersions/v3"


@pytest.mark.asyncio
async def test_an_explicit_version_is_not_replaced_by_the_current_default(tmp_path):
    """Retry keeps its saved revision even if the remote default changes."""
    client = DocumentAiClient(tmp_path / "key", "project", "eu")
    client.metadata = AsyncMock(side_effect=[{"defaultProcessorVersion": "projects/project/locations/eu/processors/p/processorVersions/new"}, {}])
    result = await resolve_extractor(client, "p/processorVersions/old")
    assert result["version"] == "old"
    assert client.metadata.call_args.args[0].endswith("/old")


@pytest.mark.asyncio
async def test_missing_metadata_permission_preserves_unknown_version(tmp_path):
    """Processing permission need not include metadata access."""
    client = DocumentAiClient(tmp_path / "key", "project", "eu")
    client.metadata = AsyncMock(side_effect=DocumentAiError("403"))
    assert (await resolve_extractor(client, "p"))["version"] is None


def test_engine_snapshot_survives_reopening_the_store(tmp_path):
    """History must not use today's processor configuration."""
    store = EvaluationStore(tmp_path / "runs.db")
    engine = {"processor_id": "p", "version": "v1", "display_name": "Invoices"}
    run = store.start(dataset="Invoices", model="Not used", prompts=PromptConfiguration(), total_documents=0, extraction_engine=engine)
    assert EvaluationStore(store.path).get_evaluation(run).extraction_engine == engine
