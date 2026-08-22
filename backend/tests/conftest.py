"""Nothing a test does may touch the data of the running application.

The API tests exercise `app.main` directly, and its stores are module-level
objects pointing at backend/data. A fixture that forgets to replace one of them
writes into the user's real settings, database or pipelines, which is how a
test run silently changed a saved pipeline once.
"""

import pytest

from app import main
from app.pipeline.store import PipelineStore


@pytest.fixture(autouse=True)
def never_touch_real_data(tmp_path, monkeypatch):
    # Nothing is written until a test writes: a directory appearing on its own
    # would break the tests that check what a store leaves on disk.
    isolated = tmp_path / ".isolated"
    pipelines = PipelineStore(isolated / "pipelines")
    monkeypatch.setattr(main, "pipeline_store", pipelines)
    monkeypatch.setattr(main, "PIPELINES_PATH", isolated / "pipelines")
    monkeypatch.setattr(main, "DATA_DIR", isolated)
    monkeypatch.setattr(main, "SETTINGS_PATH", isolated / "settings.json")
    monkeypatch.setattr(main, "DATABASE_PATH", isolated / "docuflow.db")
    monkeypatch.setattr(main, "DATASETS_PATH", isolated / "datasets")
