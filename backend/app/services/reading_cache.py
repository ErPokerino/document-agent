"""What Document AI read from a document, kept so it need not be read again.

OCR is billed per page and takes seconds a page, and a Lab experiment that
changes only a prompt sends the same pages to the same processor every time.
Training needs the same readings once more, for every document it learns from.

Two rules keep a cached reading honest:

- **Only a pinned processor version has a key.** A step that calls the
  processor's default gets whatever Google serves that day; a reading stored
  under the default would be replayed after the default moved, and the run
  would claim a reading no processor produces any longer.
- **Writing is always on; reading back is chosen.** Every pinned reading is
  stored, so the cache fills while runs measure what they always measured. A
  run that reuses readings says so, because its time and its bill are no longer
  what the pipeline costs.

The key covers the original PDF and how many of its pages were sent, so the
page limit is part of it: a two-page cut and a ten-page cut of the same PDF are
different readings. Not the bytes of the cut itself — PyMuPDF writes a fresh
document id into every copy, so the same cut made twice never hashed the same.
"""

import gzip
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PINNED = re.compile(r"/processorVersions/[A-Za-z0-9][A-Za-z0-9_.-]*$")
KEY = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CacheStats:
    entries: int
    size_bytes: int


def is_pinned(processor_id: str) -> bool:
    return bool(PINNED.search(processor_id or ""))


def reading_key(
    *,
    kind: str,
    project_id: str,
    location: str,
    processor_id: str,
    api_version: str,
    content: bytes,
    pages: int,
) -> str | None:
    """The key a reading is stored under, or None when it must not be stored."""
    if not is_pinned(processor_id):
        return None
    identity = {
        "kind": kind,
        "project_id": project_id,
        "location": location,
        "processor_id": processor_id,
        "api_version": api_version,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "pages": pages,
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReadingCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not KEY.match(key):
            raise ValueError("Invalid reading cache key")
        return self.root / key[:2] / f"{key}.json.gz"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stored:
                answer = json.load(stored)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            # A damaged entry is a miss, not a failure: the processor can
            # still be asked, and the next answer replaces it.
            path.unlink(missing_ok=True)
            return None
        return answer if isinstance(answer, dict) else None

    def put(self, key: str, answer: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".tmp") as output:
            temporary = Path(output.name)
        try:
            with gzip.open(temporary, "wt", encoding="utf-8") as stored:
                json.dump(answer, stored, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def stats(self) -> CacheStats:
        entries = 0
        size = 0
        if self.root.exists():
            for path in self.root.glob("*/*.json.gz"):
                entries += 1
                size += path.stat().st_size
        return CacheStats(entries=entries, size_bytes=size)

    def clear(self) -> int:
        removed = 0
        if self.root.exists():
            for path in self.root.glob("*/*.json.gz"):
                path.unlink(missing_ok=True)
                removed += 1
        return removed
