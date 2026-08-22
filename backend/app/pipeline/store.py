"""Saved pipelines, one JSON file each.

A folder of readable files rather than rows in the database: a pipeline is a
short document a person may want to copy between machines, diff, or hand to a
colleague, and none of that survives being a blob in SQLite.

The default pipeline is always listed, even before anything is saved, so the
app is never in a state where no pipeline can be run. Saving one under the same
name replaces it, which is how someone edits the starting point.
"""

import json
import os
from pathlib import Path

from pydantic import ValidationError

from app.pipeline.definition import SAFE_NAME, PipelineDefinition


class UnknownPipeline(LookupError):
    """No pipeline is saved under that name."""


class InvalidPipelineName(ValueError):
    """The name cannot be used as a file name."""


def _validate(name: str) -> str:
    if not isinstance(name, str) or not SAFE_NAME.match(name) or name.strip() != name:
        raise InvalidPipelineName(f"Pipeline name must be plain text without path separators: {name!r}")
    return name


class PipelineStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        return self.root / f"{_validate(name)}.json"

    def list(self) -> list[PipelineDefinition]:
        saved: list[PipelineDefinition] = []
        if self.root.exists():
            for path in sorted(self.root.glob("*.json")):
                definition = self._load(path)
                if definition is not None:
                    saved.append(definition)

        default = PipelineDefinition.default()
        if any(definition.name == default.name for definition in saved):
            return saved
        return [default, *saved]

    def read(self, name: str) -> PipelineDefinition:
        path = self._path(name)
        if path.exists():
            definition = self._load(path)
            if definition is not None:
                return definition
        default = PipelineDefinition.default()
        if name == default.name:
            return default
        raise UnknownPipeline(f"No pipeline named {name!r}")

    def save(self, definition: PipelineDefinition) -> PipelineDefinition:
        path = self._path(definition.name)
        self.root.mkdir(parents=True, exist_ok=True)
        # Write-then-rename, so an interrupted save cannot leave half a pipeline.
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(definition.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return definition

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.exists():
            raise UnknownPipeline(f"No pipeline named {name!r}")
        path.unlink()

    @staticmethod
    def _load(path: Path) -> PipelineDefinition | None:
        """None for a file we cannot read: one bad file must not hide the rest."""
        try:
            return PipelineDefinition.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValidationError):
            return None
