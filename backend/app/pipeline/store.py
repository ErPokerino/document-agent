"""Saved pipelines, one JSON file each.

A folder of readable files rather than rows in the database: a pipeline is a
short document a person may want to copy between machines, diff, or hand to a
colleague, and none of that survives being a blob in SQLite.

The default pipeline is what an empty store offers, so the app is never in a
state where no pipeline can be run. It is written out on first start and is an
ordinary file from then on: editable, renameable, and gone once deleted.
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

    def list(self) -> "list[PipelineDefinition]":
        saved = self._saved()
        return saved or [PipelineDefinition.default()]

    def read(self, name: str) -> PipelineDefinition:
        path = self._path(name)
        if path.exists():
            definition = self._load(path)
            if definition is not None:
                return definition
        # An empty store still answers for the starting point, so a fresh
        # install can run before anything has been written.
        default = PipelineDefinition.default()
        if name == default.name and not self._saved():
            return default
        raise UnknownPipeline(f"No pipeline named {name!r}")

    def seed_default(self) -> None:
        """Write the starting point out, so it can be edited like any other."""
        if not self._saved():
            self.save(PipelineDefinition.default())

    def rename(self, name: str, new_name: str) -> PipelineDefinition:
        definition = self.read(name)
        if new_name != name and self._path(new_name).exists():
            raise InvalidPipelineName(f"A pipeline named {new_name!r} already exists")
        definition.name = _validate(new_name)
        self.save(definition)
        if new_name != name:
            self._path(name).unlink(missing_ok=True)
        return definition

    def _saved(self) -> "list[PipelineDefinition]":
        if not self.root.exists():
            return []
        loaded = (self._load(path) for path in sorted(self.root.glob("*.json")))
        return [definition for definition in loaded if definition is not None]

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
