"""The registry of trained models: immutable, addressed by what they contain.

An artefact is a folder holding a manifest and the files its kind declares.
Its id is a hash of the manifest and those files, so a pipeline step that names
an id names exactly one model, and the Lab fingerprint — which hashes the
pipeline — changes whenever the model does. Nothing in a stored artefact is
ever rewritten; a model trained again is a new artefact.

The manifest records what is needed to judge the model later: the datasets and
the hash of every document it learned from (which is what refuses a Lab run
over those same documents), the reading steps that produced its text, the
parameters, the library versions and what validation measured.

Import accepts only the files a kind declares, in the formats it declares, and
recomputes the id from what arrived. A pickle is never among them.
"""

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.training import knn

ID = re.compile(r"^[0-9a-f]{32}$")
CLASSIFIER = "classifier"
# An archive is a manifest and a few arrays; anything near this is not one.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


class UnknownArtifact(LookupError):
    pass


class InvalidArtifact(ValueError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    id: str
    manifest: dict[str, Any]
    size_bytes: int


def expected_files(manifest: dict[str, Any]) -> list[str]:
    """The files a manifest's kind consists of, refusing any a kind does not declare.

    A nearest-neighbour model is a fixed set. A classifier lists its own —
    one set per field — and each name must be one a classifier can have:
    features, classes, or a model format an algorithm here writes.
    """
    from app.training.classifier import classifier_files_allowed

    kind = str(manifest.get("kind"))
    if kind == knn.KIND:
        return list(knn.FILES)
    if kind == CLASSIFIER:
        listed = [str(name) for name in manifest.get("files") or []]
        entities = [str(name) for name in manifest.get("entities") or []]
        refused = [name for name in listed if not classifier_files_allowed(name, entities)]
        if refused:
            raise InvalidArtifact(f"A classifier does not have the files: {', '.join(sorted(refused))}")
        return listed
    raise InvalidArtifact(f"{kind!r} is not a kind of model this version can run")


def runnable(manifest: dict[str, Any], files: dict[str, bytes]) -> Any:
    from app.training.classifier import ClassifierModel

    if manifest.get("kind") == CLASSIFIER:
        return ClassifierModel.from_files(files, manifest)
    return knn.KnnModel.from_files(files, knn.KnnParameters.model_validate(manifest.get("parameters") or {}))


def artifact_id(manifest: dict[str, Any], files: dict[str, bytes]) -> str:
    """The hash of what the artefact is. Its id and its name are not part of it."""
    core = {key: value for key, value in manifest.items() if key not in ("id", "name", "created_at", "imported")}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    for name in sorted(files):
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(files[name]).digest())
    return digest.hexdigest()[:32]


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._loaded: dict[str, Any] = {}

    def _dir(self, artifact: str) -> Path:
        if not ID.match(artifact or ""):
            raise UnknownArtifact(f"No trained model with id {artifact!r}")
        return self.root / artifact

    # -- reading -----------------------------------------------------------------

    def list(self) -> list[StoredArtifact]:
        if not self.root.exists():
            return []
        found = []
        for entry in self.root.iterdir():
            if entry.is_dir() and ID.match(entry.name) and (entry / "manifest.json").exists():
                try:
                    found.append(self.get(entry.name))
                except (InvalidArtifact, UnknownArtifact):
                    continue
        return sorted(found, key=lambda artifact: str(artifact.manifest.get("created_at", "")), reverse=True)

    def get(self, artifact: str) -> StoredArtifact:
        directory = self._dir(artifact)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise UnknownArtifact(f"No trained model with id {artifact}") from exc
        except ValueError as exc:
            raise InvalidArtifact(f"The manifest of {artifact} is not valid JSON") from exc
        size = sum(path.stat().st_size for path in directory.iterdir() if path.is_file())
        return StoredArtifact(id=artifact, manifest=manifest, size_bytes=size)

    def files(self, artifact: str) -> dict[str, bytes]:
        stored = self.get(artifact)
        directory = self._dir(artifact)
        return {name: (directory / name).read_bytes() for name in expected_files(stored.manifest)}

    def load(self, artifact: str) -> Any:
        """The runnable model, read once and kept: a Lab run asks for it per document."""
        if artifact not in self._loaded:
            stored = self.get(artifact)
            files = self.files(artifact)
            if artifact_id(stored.manifest, files) != artifact:
                raise InvalidArtifact(f"The files of {artifact} no longer match its id")
            try:
                self._loaded[artifact] = runnable(stored.manifest, files)
            except (ValueError, KeyError) as exc:
                raise InvalidArtifact(str(exc)) from exc
        return self._loaded[artifact]

    # -- writing -----------------------------------------------------------------

    def save(self, manifest: dict[str, Any], files: dict[str, bytes]) -> StoredArtifact:
        expected = expected_files(manifest)
        if set(files) != set(expected):
            raise InvalidArtifact(f"A {manifest.get('kind')} model is the files {', '.join(sorted(expected))}")
        identity = artifact_id(manifest, files)
        target = self._dir(identity)
        if target.exists():
            # The same model trained twice on the same data: one artefact.
            return self.get(identity)
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=self.root, prefix=".incoming-"))
        try:
            for name, content in files.items():
                (staging / name).write_bytes(content)
            (staging / "manifest.json").write_text(
                json.dumps({**manifest, "id": identity}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(staging, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self.get(identity)

    def delete(self, artifact: str) -> None:
        directory = self._dir(artifact)
        if not directory.exists():
            raise UnknownArtifact(f"No trained model with id {artifact}")
        shutil.rmtree(directory)
        self._loaded.pop(artifact, None)

    # -- moving between machines -------------------------------------------------

    def export(self, artifact: str) -> bytes:
        stored = self.get(artifact)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(stored.manifest, ensure_ascii=False, indent=2))
            for name, content in self.files(artifact).items():
                archive.writestr(name, content)
        return buffer.getvalue()

    def import_archive(self, content: bytes) -> StoredArtifact:
        if len(content) > MAX_ARCHIVE_BYTES:
            raise InvalidArtifact("The archive is larger than a trained model can be")
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise InvalidArtifact("The file is not a zip archive") from exc
        with archive:
            names = set(archive.namelist())
            if "manifest.json" not in names:
                raise InvalidArtifact("The archive has no manifest.json")
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except ValueError as exc:
                raise InvalidArtifact("manifest.json is not valid JSON") from exc
            if not isinstance(manifest, dict):
                raise InvalidArtifact("manifest.json must hold a JSON object")
            kind = str(manifest.get("kind"))
            expected = expected_files(manifest)
            unexpected = names - set(expected) - {"manifest.json"}
            if unexpected:
                raise InvalidArtifact(f"The archive holds files a {kind} model does not have: {', '.join(sorted(unexpected))}")
            missing = set(expected) - names
            if missing:
                raise InvalidArtifact(f"The archive lacks: {', '.join(sorted(missing))}")
            files = {name: archive.read(name) for name in expected}
        try:
            runnable(manifest, files)
        except (ValueError, KeyError, OSError) as exc:
            raise InvalidArtifact(f"The model files cannot be read: {exc}") from exc
        for key in ("training", "entities"):
            if key not in manifest:
                raise InvalidArtifact(f"manifest.json has no {key!r}")
        return self.save({**manifest, "imported": True}, files)


def training_hashes(manifest: dict[str, Any]) -> set[str]:
    return {str(document["sha256"]) for document in manifest.get("training", {}).get("documents", [])}
