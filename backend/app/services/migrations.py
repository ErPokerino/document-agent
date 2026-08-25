"""One-off moves of stored data that a schema change leaves behind.

Kept out of the stores themselves: a store should describe what it holds
today, not carry the history of every shape it used to have.
"""

import json
from pathlib import Path

from app.pipeline.definition import PipelineDefinition
from app.pipeline.store import PipelineStore, UnknownPipeline


def adopt_legacy_page_limit(settings_path: Path, pipelines: PipelineStore) -> None:
    """Move the app-wide page limit into the default pipeline.

    The limit used to be one number for the whole app. It belongs to a
    pipeline, so an existing install must not silently fall back to the
    default of 10 pages after an upgrade.
    """
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict) or "max_pages_to_analyze" not in data:
        return

    limit = data.pop("max_pages_to_analyze")
    default = PipelineDefinition.default()
    try:
        pipelines.read(default.name)
        already_saved = (pipelines.root / f"{default.name}.json").exists()
    except UnknownPipeline:
        already_saved = False

    # Only the untouched default is rewritten; an edited pipeline is the
    # user's own answer to the same question.
    if not already_saved and isinstance(limit, int) and 1 <= limit <= 100:
        default.page_limit = limit
        pipelines.save(default)

    Path(settings_path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# The model id DocuFlow used to ship as its default: the one installed on the
# machine it was written on. Anywhere else it names nothing.
INHERITED_MODEL_DEFAULT = "qwen/qwen3.8-27b"


def clear_inherited_model_default(
    settings_path: Path,
    installed: set[str] | None = None,
) -> None:
    """Forget a model choice that was a default rather than a decision.

    A default written into a settings file stops being a default: it becomes
    what the app opens configured for, on a machine that may never have had
    that model. Cleared once, so a later deliberate choice of the same model
    stands — which is why an install that actually has it is left alone.
    """
    path = Path(settings_path)
    # A marker beside the file rather than a key inside it: the settings model
    # forbids unknown keys, and this is a note about the file, not a setting.
    done = path.with_name(f"{path.name}.model-default-cleared")
    if done.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict) or data.get("model") != INHERITED_MODEL_DEFAULT:
        return
    if installed and INHERITED_MODEL_DEFAULT in installed:
        return

    data["model"] = ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    done.write_text("", encoding="utf-8")
