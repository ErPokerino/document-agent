"""What a clone on a machine DocuFlow has never run on gets.

Everything under backend/data is ignored by git, so a new checkout starts with
no settings, no pipelines and no database. Whatever the app assumes at that
moment is an assumption about the machine it was written on.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings
from app.pipeline.store import PipelineStore
from app.services.settings_store import SettingsStore


def test_no_model_is_chosen_for_a_machine_whose_models_are_unknown(tmp_path) -> None:
    """The default used to be a model installed on the author's laptop.

    Anywhere else that is a model id pointing at nothing, and the app opens
    already configured for a model the user does not have.
    """
    settings = SettingsStore(tmp_path / "settings.json").read()
    assert settings.model == ""


def test_the_defaults_that_do_not_depend_on_the_machine_are_still_there(tmp_path) -> None:
    settings = SettingsStore(tmp_path / "settings.json").read()
    assert settings.provider == "lm_studio"
    assert settings.lm_studio_url == "http://127.0.0.1:1234"
    assert [entity.name for entity in settings.prompts.entities]
    assert settings.prompts.system_prompt.strip()


def test_a_pipeline_exists_to_run_before_anyone_creates_one(tmp_path) -> None:
    pipelines = PipelineStore(tmp_path / "pipelines")
    names = [pipeline.name for pipeline in pipelines.list()]
    assert names, "a fresh install must offer at least one runnable pipeline"


@pytest.mark.anyio
async def test_extraction_asks_for_a_model_rather_than_failing_obscurely() -> None:
    """With nothing selected the answer has to name what is missing."""
    with pytest.raises(Exception) as raised:
        await main._ensure_model_ready(AppSettings(model=""))
    assert "model" in str(raised.value).lower()


def test_a_fresh_install_serves_its_pages(tmp_path, monkeypatch) -> None:
    """No settings file, no database: the app still answers."""
    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/pipelines").status_code == 200
        assert client.get("/api/settings").status_code == 200
