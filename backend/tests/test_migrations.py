import json

from app.pipeline.definition import PipelineDefinition
from app.pipeline.store import PipelineStore
from app.services.migrations import adopt_legacy_page_limit


def settings_file(tmp_path, **extra):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "m", **extra}), encoding="utf-8")
    return path


def test_the_old_app_wide_page_limit_becomes_the_default_pipelines_limit(tmp_path) -> None:
    path = settings_file(tmp_path, max_pages_to_analyze=3)
    store = PipelineStore(tmp_path / "pipelines")

    adopt_legacy_page_limit(path, store)

    assert store.read(PipelineDefinition.default().name).page_limit == 3
    assert "max_pages_to_analyze" not in json.loads(path.read_text(encoding="utf-8"))


def test_a_pipeline_the_user_already_saved_is_left_alone(tmp_path) -> None:
    path = settings_file(tmp_path, max_pages_to_analyze=3)
    store = PipelineStore(tmp_path / "pipelines")
    mine = PipelineDefinition.default()
    mine.page_limit = 20
    store.save(mine)

    adopt_legacy_page_limit(path, store)

    assert store.read(mine.name).page_limit == 20


def test_running_it_again_changes_nothing(tmp_path) -> None:
    path = settings_file(tmp_path, max_pages_to_analyze=3)
    store = PipelineStore(tmp_path / "pipelines")

    adopt_legacy_page_limit(path, store)
    adopt_legacy_page_limit(path, store)

    assert store.read(PipelineDefinition.default().name).page_limit == 3


def test_settings_without_the_old_key_are_not_touched(tmp_path) -> None:
    path = settings_file(tmp_path)
    before = path.read_text(encoding="utf-8")
    store = PipelineStore(tmp_path / "pipelines")

    adopt_legacy_page_limit(path, store)

    assert path.read_text(encoding="utf-8") == before
    assert store.list() == [PipelineDefinition.default()]


def test_a_missing_or_unreadable_settings_file_is_not_an_error(tmp_path) -> None:
    store = PipelineStore(tmp_path / "pipelines")
    adopt_legacy_page_limit(tmp_path / "absent.json", store)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    adopt_legacy_page_limit(broken, store)
