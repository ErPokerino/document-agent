"""A native PDF already carries its text; reading it needs nothing from Google."""

import pymupdf
import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction, PromptConfiguration
from app.pipeline.compiler import build_steps
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind, describe_problems
from app.pipeline.engine import PipelineContext
from app.pipeline.steps import InspectPdf, ReadPdfText
from app.services.text_boxes import locate_value


def pdf(*pages: str | None) -> bytes:
    """One page per argument; None is a page with no text, as a scan has."""
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 100), text)
    data = document.tobytes()
    document.close()
    return data


async def read(content: bytes, *, feeds_model: bool = True, page_limit: int = 10) -> PipelineContext:
    context = PipelineContext(
        filename="invoice.pdf", content=content, model="m", lm_studio_url="http://x"
    )
    await InspectPdf(page_limit=page_limit).run(context)
    await ReadPdfText(feeds_model=feeds_model).run(context)
    return context


@pytest.mark.asyncio
async def test_the_text_of_each_page_is_given_to_the_model_page_by_page() -> None:
    context = await read(pdf("Invoice 2026/041", "Total due 1.220,00"))

    assert "[Page 1]\nInvoice 2026/041" in context.artifacts["text"]
    assert "[Page 2]\nTotal due 1.220,00" in context.artifacts["text"]


@pytest.mark.asyncio
async def test_a_document_with_no_text_is_refused_rather_than_read_as_empty() -> None:
    """An empty reading passed on would have the model answer from nothing."""
    with pytest.raises(ValueError, match="scanned"):
        await read(pdf(None, None))


@pytest.mark.asyncio
async def test_a_page_without_text_is_named_rather_than_skipped() -> None:
    context = await read(pdf("Invoice 41", None))

    assert "[Page 2 carries no embedded text.]" in context.artifacts["text"]
    assert context.artifacts["pdf_text_pages"] == [
        {"page": 1, "characters": len("Invoice 41")},
        {"page": 2, "characters": 0},
    ]


@pytest.mark.asyncio
async def test_only_the_pages_the_pipeline_allows_are_read() -> None:
    context = await read(pdf("first", "second", "third"), page_limit=2)

    assert "third" not in context.artifacts["text"]
    assert len(context.artifacts["pdf_text_pages"]) == 2


@pytest.mark.asyncio
async def test_the_words_carry_boxes_so_values_can_be_highlighted() -> None:
    """The same tokens OCR leaves behind, so highlighting needs no Google call."""
    context = await read(pdf("Invoice number 2026/041"))
    tokens = context.artifacts["ocr_tokens"]

    found = locate_value("2026/041", tokens)

    assert found is not None
    assert found.page == 0
    assert 0 < found.box.left < found.box.right <= 1
    assert 0 < found.box.top < found.box.bottom <= 1


def test_a_total_stored_as_a_float_is_found_where_the_page_prints_its_cents() -> None:
    """1220.0 was looked for as 1.220,0, so no printed total was ever highlighted."""
    from app.services.text_boxes import Box, TextToken

    tokens = [TextToken("Total", 0, Box(0, 0, 0.1, 0.1)), TextToken("1.220,00", 0, Box(0.2, 0, 0.3, 0.1))]

    assert locate_value(1220.0, tokens) is not None
    assert locate_value(1220.5, [TextToken("1.220,50", 0, Box(0, 0, 0.1, 0.1))]) is not None


@pytest.mark.asyncio
async def test_a_reading_for_positions_only_gives_the_model_no_text() -> None:
    context = await read(pdf("Invoice 41"), feeds_model=False)

    assert "text" not in context.artifacts
    assert context.artifacts["ocr_tokens"]


def test_a_text_model_can_read_what_the_pdf_carries() -> None:
    definition = PipelineDefinition(
        name="Native text",
        steps=[PipelineStep(kind=StepKind.read_pdf_text), PipelineStep(kind=StepKind.llm_extract)],
    )

    assert describe_problems(definition) == []
    steps = build_steps(definition, prompts=PromptConfiguration(), entities=[])
    assert isinstance(steps[1], ReadPdfText)


def test_reading_the_pdf_text_is_not_a_cloud_step() -> None:
    from app.services.processors import KINDS

    assert StepKind.read_pdf_text.value not in KINDS
