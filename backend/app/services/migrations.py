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
