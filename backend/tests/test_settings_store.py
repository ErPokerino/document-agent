import json

import pytest

from app.domain.models import AppSettings
from app.services import settings_store as settings_store_module
from app.services.settings_store import SettingsStore


def test_corrupted_settings_file_falls_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"model": "half-written', encoding="utf-8")

    settings = SettingsStore(path).read()

    assert settings.model == AppSettings().model
    assert [entity.name for entity in settings.prompts.entities] == [
        entity.name for entity in AppSettings().prompts.entities
    ]


def test_corrupted_settings_file_is_kept_for_inspection(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not json at all", encoding="utf-8")

    SettingsStore(path).read()

    assert path.with_suffix(".corrupt.json").read_text(encoding="utf-8") == "not json at all"


def test_settings_that_no_longer_validate_fall_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "chartreuse"}), encoding="utf-8")

    assert SettingsStore(path).read().theme == AppSettings().theme


def test_the_page_limit_that_moved_to_pipelines_does_not_invalidate_the_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"model": "kept", "max_pages_to_analyze": 3}), encoding="utf-8")

    # Dropping the key must not take the rest of the settings with it.
    assert SettingsStore(path).read().model == "kept"


def test_a_failed_write_leaves_the_previous_settings_readable(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.write(AppSettings(model="original-model"))

    def failing_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(settings_store_module.os, "replace", failing_replace)
    with pytest.raises(OSError):
        store.write(AppSettings(model="new-model"))

    assert store.read().model == "original-model"


def test_writing_leaves_no_temporary_file_behind(tmp_path) -> None:
    path = tmp_path / "settings.json"
    SettingsStore(path).write(AppSettings())

    assert [entry.name for entry in tmp_path.iterdir()] == ["settings.json"]


def test_entity_without_a_description_does_not_break_the_store(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "model": "vision-model",
                "prompts": {"entities": [{"name": "custom_field", "format": "text"}]},
            }
        ),
        encoding="utf-8",
    )

    settings = SettingsStore(path).read()

    assert settings.model == AppSettings().model


def test_a_thinking_level_no_model_accepts_is_migrated_rather_than_lost(tmp_path) -> None:
    """The API knows MINIMAL; Gemini 3.7 Flash answers 400 for it.

    A stored "minimal" would fail every extraction, and dropping the whole
    settings file over one stale value would be worse.
    """
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"model": "kept", "gemini": {"thinking_level": "minimal"}}), encoding="utf-8"
    )

    settings = SettingsStore(path).read()

    assert settings.gemini.thinking_level == "low"
    assert settings.model == "kept"
