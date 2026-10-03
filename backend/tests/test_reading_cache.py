"""Document AI readings kept for reuse, and the rules that keep reuse honest."""

import pytest
import pymupdf
from fastapi.testclient import TestClient

from app.api import deps
from app.main import app
from app.pipeline.engine import PipelineContext
from app.pipeline.steps import ReadWithDocumentAi
from app.services.reading_cache import ReadingCache, reading_key

PINNED = "projects/p/locations/eu/processors/ocr/processorVersions/pretrained-ocr-v2.0-2023-06-02"


def make_pdf(pages: int = 2) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        document.new_page().insert_text((72, 72), f"Page {index + 1}")
    data = document.tobytes()
    document.close()
    return data


PDF = make_pdf()


def context(cache: ReadingCache | None, *, reuse: bool, processed: int = 1) -> PipelineContext:
    ctx = PipelineContext(
        filename="a.pdf",
        content=PDF,
        model="m",
        lm_studio_url="http://localhost:1234",
        gcp_project_id="p",
        gcp_location="eu",
        reading_cache=cache,
        reuse_readings=reuse,
    )
    ctx.artifacts.update({"page_count": 2, "processed_pages": processed})
    return ctx


class CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, processor_id: str, content: bytes) -> dict:
        self.calls += 1
        return {"document": {"text": f"ACME LTD reading {self.calls}"}}


def ocr_step(client: CountingClient, processor_id: str = PINNED) -> ReadWithDocumentAi:
    step = ReadWithDocumentAi("document_ai_ocr", processor_id)
    step._client = lambda ctx: client  # type: ignore[method-assign]
    return step


def test_a_processor_without_a_pinned_version_has_no_key() -> None:
    """Google's default version can move; a reading stored under it would outlive it."""
    assert reading_key(
        kind="document_ai_ocr", project_id="p", location="eu",
        processor_id="projects/p/locations/eu/processors/ocr", api_version="v1", content=b"x", pages=1,
    ) is None


def test_the_page_limit_is_part_of_the_key() -> None:
    """A two-page cut and a one-page cut of one PDF are different readings."""
    common = dict(kind="document_ai_ocr", project_id="p", location="eu", processor_id=PINNED, api_version="v1")
    assert reading_key(**common, content=b"pdf", pages=1) != reading_key(**common, content=b"pdf", pages=2)


@pytest.mark.asyncio
async def test_a_run_that_does_not_reuse_readings_still_stores_them(tmp_path) -> None:
    """The cache fills while runs go on measuring what the pipeline costs."""
    cache = ReadingCache(tmp_path)
    client = CountingClient()
    step = ocr_step(client)

    first = context(cache, reuse=False)
    await step.run(first)
    second = context(cache, reuse=False)
    await step.run(second)

    assert client.calls == 2
    assert cache.stats().entries == 1
    assert second.artifacts["document_ai_pages"] == {"document_ai_ocr": 1}
    assert "cached_pages" not in second.artifacts


@pytest.mark.asyncio
async def test_a_reused_reading_is_not_counted_as_a_billed_page(tmp_path) -> None:
    cache = ReadingCache(tmp_path)
    client = CountingClient()
    step = ocr_step(client)
    await step.run(context(cache, reuse=False))

    reused = context(cache, reuse=True)
    await step.run(reused)

    assert client.calls == 1
    assert reused.artifacts["document_text"] == "ACME LTD reading 1"
    assert reused.artifacts["cached_pages"] == {"document_ai_ocr": 1}
    assert "document_ai_pages" not in reused.artifacts


@pytest.mark.asyncio
async def test_an_unpinned_processor_is_always_asked(tmp_path) -> None:
    cache = ReadingCache(tmp_path)
    client = CountingClient()
    step = ocr_step(client, "projects/p/locations/eu/processors/ocr")

    await step.run(context(cache, reuse=True))
    await step.run(context(cache, reuse=True))

    assert client.calls == 2
    assert cache.stats().entries == 0


@pytest.mark.asyncio
async def test_the_same_cut_of_the_same_pdf_finds_its_reading(tmp_path) -> None:
    """A cut is rewritten on every run, with a fresh document id inside it."""
    cache = ReadingCache(tmp_path)
    client = CountingClient()
    step = ocr_step(client)
    await step.run(context(cache, reuse=True, processed=1))
    await step.run(context(cache, reuse=True, processed=1))
    await step.run(context(cache, reuse=True, processed=2))

    assert client.calls == 2


@pytest.mark.asyncio
async def test_positions_only_still_leaves_the_text_that_was_read(tmp_path) -> None:
    """A step that predicts from the document's text needs it even when the model is not shown it."""
    step = ReadWithDocumentAi("document_ai_ocr", PINNED, feeds_model=False)
    step._client = lambda ctx: CountingClient()  # type: ignore[method-assign]
    ctx = context(None, reuse=False)
    await step.run(ctx)

    assert "text" not in ctx.artifacts
    assert ctx.artifacts["document_text"] == "ACME LTD reading 1"


def test_a_damaged_entry_reads_as_a_miss(tmp_path) -> None:
    cache = ReadingCache(tmp_path)
    key = "a" * 64
    path = tmp_path / "aa" / f"{key}.json.gz"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not gzip")

    assert cache.get(key) is None
    assert not path.exists()


def test_the_cache_can_be_measured_and_emptied_from_the_api() -> None:
    deps.reading_cache.put("b" * 64, {"document": {"text": "x"}})
    client = TestClient(app)

    assert client.get("/api/reading-cache").json()["entries"] == 1
    assert client.delete("/api/reading-cache").status_code == 204
    assert client.get("/api/reading-cache").json() == {"entries": 0, "size_bytes": 0}
