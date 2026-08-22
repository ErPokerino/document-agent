"""The Document AI steps, without touching Google."""

import pytest
import pymupdf

from app.pipeline.engine import PipelineContext
from app.pipeline.steps import ReadWithDocumentAi
from app.services.document_ai import DocumentAiError


def pdf_bytes(pages: int = 3) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        document.new_page().insert_text((72, 72), f"Page {index + 1}")
    data = document.tobytes()
    document.close()
    return data


def context(pages: int = 3, processed: int = 1) -> PipelineContext:
    ctx = PipelineContext(
        filename="a.pdf",
        content=pdf_bytes(pages),
        model="m",
        lm_studio_url="http://localhost:1234",
        gcp_credentials_path="key.json",
        gcp_project_id="a-project",
        gcp_location="eu",
    )
    ctx.artifacts.update({"page_count": pages, "processed_pages": processed})
    return ctx


class FakeClient:
    """Records what it was asked to process, and answers with fixed content."""

    def __init__(self, answer: dict) -> None:
        self.answer = answer
        self.sent: list[bytes] = []
        self.processors: list[str] = []

    async def process(self, processor_id: str, content: bytes) -> dict:
        self.processors.append(processor_id)
        self.sent.append(content)
        return self.answer


@pytest.mark.asyncio
async def test_ocr_leaves_the_text_it_read(monkeypatch) -> None:
    client = FakeClient({"document": {"text": "ACME LTD\nInvoice 7\n"}})
    step = ReadWithDocumentAi("document_ai_ocr", "ocr-id")
    monkeypatch.setattr(step, "_client", lambda ctx: client)

    ctx = context()
    await step.run(ctx)

    assert ctx.artifacts["text"] == "ACME LTD\nInvoice 7\n"
    assert client.processors == ["ocr-id"]


@pytest.mark.asyncio
async def test_the_layout_parser_leaves_text_and_the_structure(monkeypatch) -> None:
    layout = {"blocks": [{"textBlock": {"text": "ACME LTD", "type": "heading-1"}}]}
    client = FakeClient({"document": {"documentLayout": layout}})
    step = ReadWithDocumentAi("document_ai_layout", "layout-id")
    monkeypatch.setattr(step, "_client", lambda ctx: client)

    ctx = context()
    await step.run(ctx)

    assert ctx.artifacts["text"] == "# ACME LTD"
    assert ctx.artifacts["layout"] == layout


@pytest.mark.asyncio
async def test_only_the_pages_the_pipeline_asked_for_are_sent(monkeypatch) -> None:
    """Document AI is billed per page, so a page limit has to be a real limit."""
    client = FakeClient({"document": {"text": "x"}})
    step = ReadWithDocumentAi("document_ai_ocr", "ocr-id")
    monkeypatch.setattr(step, "_client", lambda ctx: client)

    await step.run(context(pages=5, processed=2))

    sent = pymupdf.open(stream=client.sent[0], filetype="pdf")
    try:
        assert sent.page_count == 2
    finally:
        sent.close()


@pytest.mark.asyncio
async def test_the_pages_processed_are_counted_so_the_cost_can_be_worked_out(monkeypatch) -> None:
    client = FakeClient({"document": {"text": "x"}})
    step = ReadWithDocumentAi("document_ai_ocr", "ocr-id")
    monkeypatch.setattr(step, "_client", lambda ctx: client)

    ctx = context(pages=5, processed=2)
    await step.run(ctx)

    assert ctx.artifacts["document_ai_pages"] == {"document_ai_ocr": 2}


@pytest.mark.asyncio
async def test_two_readers_in_one_pipeline_both_count(monkeypatch) -> None:
    client = FakeClient({"document": {"text": "x"}})
    ctx = context(pages=5, processed=2)

    for kind, processor in (("document_ai_ocr", "ocr-id"), ("document_ai_layout", "layout-id")):
        step = ReadWithDocumentAi(kind, processor)
        monkeypatch.setattr(step, "_client", lambda ctx, client=client: client)
        await step.run(ctx)

    assert ctx.artifacts["document_ai_pages"] == {"document_ai_ocr": 2, "document_ai_layout": 2}


@pytest.mark.asyncio
async def test_a_step_with_no_processor_configured_says_so() -> None:
    with pytest.raises(DocumentAiError, match="processor"):
        await ReadWithDocumentAi("document_ai_ocr", "").run(context())
