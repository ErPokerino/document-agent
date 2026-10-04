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
    from app.services.reading_cache import ReadingCache

    monkeypatch.setattr(deps, "READING_CACHE_PATH", isolated / "reading-cache")
    monkeypatch.setattr(deps, "reading_cache", ReadingCache(isolated / "reading-cache"))
    from app.training.artifacts import ArtifactStore
    from app.training.jobs import TrainingJobs

    monkeypatch.setattr(deps, "ARTIFACTS_PATH", isolated / "artifacts")
    monkeypatch.setattr(deps, "EXPORTS_PATH", isolated / "training-exports")
    monkeypatch.setattr(deps, "artifact_store", ArtifactStore(isolated / "artifacts"))
    monkeypatch.setattr(deps, "training_jobs", TrainingJobs())
    from app.evaluation.experiments import ExperimentStore

    class Lazy:
        """Opened on first use: opening a database creates its folder."""

        def __init__(self) -> None:
            self.store = None

        def __getattr__(self, name):
            if self.store is None:
                self.store = ExperimentStore(isolated / "experiments.db")
            return getattr(self.store, name)

    monkeypatch.setattr(deps, "experiment_store", Lazy())
