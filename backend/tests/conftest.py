"""Nothing a test does may touch the data of the running application.

The API tests exercise `app.main` directly, and the stores its routers share
are module-level objects in `app.api.deps` pointing at backend/data. A fixture that forgets to replace one of them
writes into the user's real settings, database or pipelines, which is how a
test run silently changed a saved pipeline once.

With DOCUFLOW_TEST_DATABASE_URL set to a PostgreSQL address (CI does), every
test gets a schema of its own there and the stores write to it, so the suite
proves the PostgreSQL path as well as SQLite's.
"""

import os
import uuid
from urllib.parse import quote

import pytest

from app.api import deps
from app.pipeline.store import PipelineStore


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("DOCUFLOW_TEST_DATABASE_URL", "").strip():
        return
    skip = pytest.mark.skip(reason="Exercises SQLite itself; this run is against PostgreSQL")
    for item in items:
        if item.get_closest_marker("sqlite_only"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    url = os.environ.get("DOCUFLOW_TEST_DATABASE_URL", "").strip()
    if not url:
        yield None
        return
    import psycopg

    from app.services import db

    schema = f"t_{uuid.uuid4().hex[:16]}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(f"CREATE SCHEMA {schema}")
    separator = "&" if "?" in url else "?"
    monkeypatch.setenv("DOCUFLOW_DATABASE_URL", f"{url}{separator}options={quote(f'-csearch_path={schema}')}")
    try:
        yield schema
    finally:
        db.close_pools()
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture(autouse=True)
def never_touch_real_data(database, tmp_path, tmp_path_factory, monkeypatch):
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

    monkeypatch.setattr(deps, "ARTIFACTS_PATH", isolated / "artifacts")
    monkeypatch.setattr(deps, "EXPORTS_PATH", isolated / "training-exports")
    monkeypatch.setattr(deps, "artifact_store", ArtifactStore(isolated / "artifacts"))
    from app.evaluation.experiments import ExperimentStore

    from app.jobs.queue import InProcessJobs
    from app.jobs.store import JobStore

    class Lazy:
        """Opened on first use: opening a database creates its folder."""

        def __init__(self, open_store) -> None:
            self.open_store = open_store
            self.store = None

        def __getattr__(self, name):
            if self.store is None:
                self.store = self.open_store()
            return getattr(self.store, name)

    monkeypatch.setattr(deps, "experiment_store", Lazy(lambda: ExperimentStore(isolated / "experiments.db")))
    monkeypatch.setattr(deps, "job_store", Lazy(lambda: JobStore(isolated / "jobs.db")))
    monkeypatch.setattr(deps, "jobs", InProcessJobs())

    if database:
        # The module-level stores made their tables in SQLite at import; in
        # this test's schema they have to be made again.
        from app.evaluation.store import EvaluationStore
        from app.services.master_data import MasterDataStore
        from app.services.run_store import RunStore
        from app.services.supplier_rules import SupplierRuleStore

        # Outside tmp_path, which some tests list.
        beside = tmp_path_factory.mktemp("postgres-stores") / "docuflow.db"
        monkeypatch.setattr(deps, "run_store", RunStore(beside))
        monkeypatch.setattr(deps, "evaluation_store", EvaluationStore(beside))
        monkeypatch.setattr(deps, "master_data_store", MasterDataStore(beside))
        monkeypatch.setattr(deps, "supplier_rule_store", SupplierRuleStore(beside))
