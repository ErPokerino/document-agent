"""Cancellation reaches the work in flight, not only the next document."""

import asyncio

import httpx
import pytest

from app import main
from app.domain.models import AppSettings, ModelInfo, PromptConfiguration
from app.evaluation.store import EvaluationStore
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore


class ReadyClient:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        return [
            ModelInfo(
                id="vision-model",
                name="Vision model",
                loaded=True,
                profile_matches=True,
            )
        ]


@pytest.mark.asyncio
async def test_workspace_cancel_cancels_the_pipeline_task(tmp_path, monkeypatch) -> None:
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "run_store", RunStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(main, "LMStudioClient", ReadyClient)
    main.model_runtime_states["vision-model"] = "ready"
    main.release_model_operation()
    main.active_document_task = None

    entered = asyncio.Event()
    interrupted = asyncio.Event()

    class SlowPipeline:
        async def run(self, context):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                interrupted.set()
                raise

    monkeypatch.setattr(main, "_document_pipeline", lambda settings: SlowPipeline())

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        extraction = asyncio.create_task(
            client.post(
                "/api/documents/extract",
                files={"file": ("invoice.pdf", b"%PDF-1.4", "application/pdf")},
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)

        cancelled = await client.post("/api/documents/extract/cancel")
        response = await asyncio.wait_for(extraction, timeout=1)

    assert cancelled.status_code == 202
    assert cancelled.json() == {"status": "cancelling"}
    assert response.status_code == 499
    assert interrupted.is_set()
    assert main.active_model_operation is None
    assert main.active_document_task is None
    main.model_runtime_states.clear()


@pytest.mark.asyncio
async def test_lab_cancel_cancels_the_current_evaluation_task(tmp_path, monkeypatch) -> None:
    store = EvaluationStore(tmp_path / "docuflow.db")
    monkeypatch.setattr(main, "evaluation_store", store)
    evaluation_id = store.start(
        dataset="invoices",
        model="vision-model",
        prompts=PromptConfiguration(),
        total_documents=1,
    )
    main.evaluation_cancelled = asyncio.Event()
    interrupted = asyncio.Event()

    async def slow_evaluation() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise

    main.evaluation_task = asyncio.create_task(slow_evaluation())
    await asyncio.sleep(0)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/api/evaluations/{evaluation_id}/cancel")
        await asyncio.sleep(0)

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    assert main.evaluation_cancelled.is_set()
    assert interrupted.is_set()
    assert main.evaluation_task.cancelled()
    main.evaluation_task = None
    main.evaluation_cancelled = None
