"""Nothing a test does may touch the data of the running application.

The API tests exercise `app.main` directly, and the stores its routers share
are module-level objects in `app.api.deps` pointing at backend/data. A fixture that forgets to replace one of them
writes into the user's real settings, database or pipelines, which is how a
test run silently changed a saved pipeline once.
"""

import pytest

from app.api import deps
from app.pipeline.store import PipelineStore


@pytest.fixture(autouse=True)
def never_touch_real_data(tmp_path, monkeypatch):
    # Nothing is written until a test writes: a directory appearing on its own
    # would break the tests that check what a store leaves on disk.
    isolated = tmp_path / ".isolated"
    pipelines = PipelineStore(isolated / "pipelines")
    monkeypatch.setattr(deps, "pipeline_store", pipelines)
    monkeypatch.setattr(deps, "PIPELINES_PATH", isolated / "pipelines")
    monkeypatch.setattr(deps, "DATA_DIR", isolated)
    monkeypatch.setattr(deps, "SETTINGS_PATH", isolated / "settings.json")
    monkeypatch.setattr(deps, "DATABASE_PATH", isolated / "docuflow.db")
    monkeypatch.setattr(deps, "DATASETS_PATH", isolated / "datasets")
