"""A remote reader that fails is reported as the provider's failure, not as ours."""

import httpx
import pytest

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.services.document_ai import DocumentAiError
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore


class ReadyClient:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        return [ModelInfo(id="vision-model", name="Vision model", loaded=True, profile_matches=True)]


class FailingPipeline:
    async def run(self, context):
        raise DocumentAiError("Document AI returned 403: permission denied")


@pytest.mark.asyncio
async def test_a_document_ai_failure_is_a_bad_gateway_with_its_message(tmp_path, monkeypatch) -> None:
    """`DocumentAiError` was not caught, so OCR failures reached the UI as a bare 500."""
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "run_store", RunStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(main, "LMStudioClient", ReadyClient)
    monkeypatch.setattr(main, "_document_pipeline", lambda settings: FailingPipeline())
    main.model_runtime_states["vision-model"] = "ready"
    main.release_model_operation()

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/documents/extract",
            files={"file": ("invoice.pdf", b"%PDF-1.4", "application/pdf")},
        )

    assert response.status_code == 502
    assert "permission denied" in response.json()["detail"]
    assert main.active_model_operation is None
    main.model_runtime_states.clear()
