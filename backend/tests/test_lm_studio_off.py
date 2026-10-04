"""A deployment without LM Studio says so, instead of reporting it unreachable."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import deps
from app.domain.models import AppSettings
from app.services.settings_store import SettingsStore


@pytest.fixture
def no_lm_studio(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUFLOW_LM_STUDIO", "off")
    monkeypatch.delenv("DOCUFLOW_MODEL_SERVER_URL", raising=False)
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="gemma"))
    monkeypatch.setattr(deps, "settings_store", settings)

    class Unreachable:
        def __init__(self, base_url):
            raise AssertionError("LM Studio must not be asked where it is switched off")

    monkeypatch.setattr(deps, "LMStudioClient", Unreachable)


def test_health_reports_no_lm_studio_and_no_fault(no_lm_studio) -> None:
    health = TestClient(main.app).get("/api/health").json()

    assert health["status"] == "ok"
    assert health["lm_studio_enabled"] is False
    assert health["lm_studio_error"] is None


def test_models_list_only_what_this_deployment_has(no_lm_studio) -> None:
    models = TestClient(main.app).get("/api/models").json()

    assert models and all(model["provider"] != "lm_studio" for model in models)


def test_nothing_is_loaded_and_no_lm_studio_model_is_ready(no_lm_studio) -> None:
    client = TestClient(main.app)

    assert client.post("/api/models/load", json={"model": "gemma"}).status_code == 400
    assert client.get("/api/runtime-engine").json()["engine"] is None


@pytest.mark.asyncio
async def test_a_run_on_an_lm_studio_model_is_refused_with_the_reason(no_lm_studio) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refused:
        await deps.ensure_model_ready(AppSettings(provider="lm_studio", model="gemma"))
    assert "not part of this deployment" in refused.value.detail
