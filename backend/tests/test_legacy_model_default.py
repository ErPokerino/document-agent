"""Clearing a model choice nobody made.

DocuFlow shipped with a model id as the default: the one installed on the
machine it was written on. Any install created before that was removed has it
written into its settings file, where a default becomes a stored choice — so
a fresh machine opens configured for a model it does not have, and shows its
name in the header as if someone had picked it.
"""

import json
from pathlib import Path

from app.services.migrations import clear_inherited_model_default
from app.services.settings_store import SettingsStore


LEGACY = "qwen/qwen3.8-27b"


def write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_shipped_default_is_cleared(tmp_path) -> None:
    path = write(tmp_path / "settings.json", {"model": LEGACY, "provider": "lm_studio"})
    clear_inherited_model_default(path)
    assert json.loads(path.read_text(encoding="utf-8"))["model"] == ""


def test_a_model_the_machine_actually_has_is_left_alone(tmp_path) -> None:
    """Someone running that model deliberately keeps it."""
    path = write(tmp_path / "settings.json", {"model": LEGACY, "provider": "lm_studio"})
    clear_inherited_model_default(path, installed={LEGACY, "other"})
    assert json.loads(path.read_text(encoding="utf-8"))["model"] == LEGACY


def test_any_other_choice_is_never_touched(tmp_path) -> None:
    path = write(tmp_path / "settings.json", {"model": "gemini-3.7-flash"})
    clear_inherited_model_default(path)
    assert json.loads(path.read_text(encoding="utf-8"))["model"] == "gemini-3.7-flash"


def test_it_runs_once_and_not_again(tmp_path) -> None:
    """Having cleared it, a later deliberate choice of the same model stands."""
    path = write(tmp_path / "settings.json", {"model": LEGACY})
    clear_inherited_model_default(path)
    reconfigured = json.loads(path.read_text(encoding="utf-8"))
    reconfigured["model"] = LEGACY
    write(path, reconfigured)
    clear_inherited_model_default(path)
    assert json.loads(path.read_text(encoding="utf-8"))["model"] == LEGACY


def test_a_missing_or_broken_file_is_not_a_crash_on_startup(tmp_path) -> None:
    clear_inherited_model_default(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    clear_inherited_model_default(broken)


def test_the_rest_of_the_settings_survive(tmp_path) -> None:
    path = write(
        tmp_path / "settings.json",
        {"model": LEGACY, "pipeline": "OCR then model", "gemini": {"api_key": "secret"}},
    )
    clear_inherited_model_default(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["pipeline"] == "OCR then model"
    assert data["gemini"]["api_key"] == "secret"
    # And the file still loads as settings afterwards.
    assert SettingsStore(path).read().pipeline == "OCR then model"
