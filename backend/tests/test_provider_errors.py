"""A remote reader that fails is reported as the provider's failure, not as ours."""

import httpx
import pytest

from app import main
from app.api import deps
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
    async def run(self, context, on_step=None):
        raise DocumentAiError("Document AI returned 403: permission denied")


@pytest.mark.asyncio
async def test_a_document_ai_failure_is_a_bad_gateway_with_its_message(tmp_path, monkeypatch) -> None:
    """`DocumentAiError` was not caught, so OCR failures reached the UI as a bare 500."""
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(deps, "settings_store", settings)
    monkeypatch.setattr(deps, "run_store", RunStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(deps, "LMStudioClient", ReadyClient)
    monkeypatch.setattr(deps, "document_pipeline", lambda settings: FailingPipeline())
    deps.model_runtime_states["vision-model"] = "ready"
    deps.release_model_operation()

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/documents/extract",
            files={"file": ("invoice.pdf", b"%PDF-1.4", "application/pdf")},
        )

    assert response.status_code == 502
    assert "permission denied" in response.json()["detail"]
    assert deps.active_model_operation is None
    deps.model_runtime_states.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", [True, False])
async def test_only_a_lost_runtime_takes_the_model_out_of_ready(tmp_path, monkeypatch, lost) -> None:
    """Decided from LM Studio's own words, not by matching the friendlier message."""
    from app.services.lm_studio import LMStudioError

    class LosesTheRuntime:
        async def run(self, context, on_step=None):
            raise LMStudioError("LM Studio rejected the request", runtime_lost=lost)

    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(deps, "settings_store", settings)
    monkeypatch.setattr(deps, "run_store", RunStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(deps, "LMStudioClient", ReadyClient)
    monkeypatch.setattr(deps, "document_pipeline", lambda settings: LosesTheRuntime())
    deps.model_runtime_states["vision-model"] = "ready"
    deps.release_model_operation()

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/documents/extract",
            files={"file": ("invoice.pdf", b"%PDF-1.4", "application/pdf")},
        )

    assert response.status_code == 502
    assert deps.model_runtime_states["vision-model"] == ("error" if lost else "ready")
    deps.model_runtime_states.clear()


def test_lm_studio_says_when_its_runtime_is_gone() -> None:
    from app.services.lm_studio import LMStudioClient

    assert LMStudioClient._runtime_lost('{"error": "terminated"}')
    assert LMStudioClient._runtime_lost("vk::DeviceLostError: ErrorDeviceLost")
    assert not LMStudioClient._runtime_lost('{"error": "context length exceeded"}')
