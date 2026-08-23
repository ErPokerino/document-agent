import pymupdf
import pytest

from app.domain.models import FieldExtraction, PromptConfiguration
from app.pipeline.engine import DocumentPipeline, PipelineContext
from app.pipeline.steps import ExtractConfiguredEntities, InspectPdf


def make_pdf(pages: int = 1) -> bytes:
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), f"Invoice page {index + 1}")
    data = document.tobytes()
    document.close()
    return data


def make_context(pages: int) -> PipelineContext:
    return PipelineContext(
        filename="invoice.pdf",
        content=make_pdf(pages),
        model="vision-model",
        lm_studio_url="http://localhost:1234",
    )


@pytest.mark.asyncio
async def test_large_document_is_cut_to_first_pages() -> None:
    result = await DocumentPipeline([InspectPdf(page_limit=4)]).run(make_context(12))
    assert result.artifacts["page_count"] == 12
    assert result.artifacts["processed_pages"] == 4
    assert result.artifacts["first_processed_page"] == 1
    assert result.artifacts["last_processed_page"] == 4
    assert result.artifacts["cut_applied"] is True


@pytest.mark.asyncio
async def test_short_document_does_not_report_a_cut() -> None:
    context = make_context(3)
    await InspectPdf(page_limit=4).run(context)
    assert context.artifacts["processed_pages"] == 3
    assert context.artifacts["last_processed_page"] == 3
    assert context.artifacts["cut_applied"] is False


@pytest.mark.asyncio
async def test_pdf_safety_limit_is_explicit() -> None:
    with pytest.raises(ValueError, match="at most"):
        await InspectPdf(max_pages=4, page_limit=4).run(make_context(5))


@pytest.mark.asyncio
async def test_configured_page_limit_is_the_only_automatic_cut() -> None:
    context = make_context(12)
    await InspectPdf(max_pages_to_analyze=6).run(context)

    assert context.artifacts["page_limit"] == 6
    assert context.artifacts["processed_pages"] == 6
    assert context.artifacts["configured_page_limit"] == 6


@pytest.mark.asyncio
async def test_short_document_uses_all_pages_below_configured_limit() -> None:
    context = make_context(12)
    await InspectPdf(max_pages_to_analyze=20).run(context)

    assert context.artifacts["processed_pages"] == 12
    assert context.artifacts["cut_applied"] is False


@pytest.mark.asyncio
async def test_extraction_uses_one_call_for_all_processed_pages(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
            calls.append(
                {
                    "model": model,
                    "image_count": len(images),
                    "page_range": page_range,
                    "total_pages": total_pages,
                    "processed_pages": processed_pages,
                }
            )
            return {
                entity.name: FieldExtraction(value=None, confidence="low")
                for entity in prompts.entities
            }

    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", FakeClient)
    context = make_context(12)
    result = await DocumentPipeline(
        [InspectPdf(page_limit=4), ExtractConfiguredEntities(PromptConfiguration())]
    ).run(context)

    assert calls == [
        {
            "model": "vision-model",
            "image_count": 4,
            "page_range": "1-4",
            "total_pages": 12,
            "processed_pages": 4,
        }
    ]
    assert set(result.artifacts["extraction"]) == {
        "date",
        "document_number",
        "supplier_name",
        "currency",
        "total_amount",
    }


@pytest.mark.asyncio
async def test_rendering_stops_when_the_image_budget_is_exhausted(monkeypatch) -> None:
    from app.pipeline import steps

    class UnusedClient:
        def __init__(self, base_url: str) -> None:
            raise AssertionError("the model must not be called when rendering is refused")

    monkeypatch.setattr(steps, "MAX_TOTAL_IMAGE_BYTES", 512)
    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", UnusedClient)

    context = make_context(40)
    await InspectPdf(page_limit=40).run(context)

    with pytest.raises(ValueError, match="page limit"):
        await ExtractConfiguredEntities(PromptConfiguration()).run(context)


@pytest.mark.asyncio
async def test_a_document_within_the_image_budget_is_rendered(monkeypatch) -> None:
    from app.pipeline import steps

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
            return {entity.name: FieldExtraction(value=None, confidence="low") for entity in prompts.entities}

    monkeypatch.setattr(steps, "MAX_TOTAL_IMAGE_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr("app.pipeline.steps.LMStudioClient", FakeClient)

    context = make_context(2)
    await InspectPdf(page_limit=2).run(context)
    await ExtractConfiguredEntities(PromptConfiguration()).run(context)

    assert set(context.artifacts["extraction"]) == {
        "date",
        "document_number",
        "supplier_name",
        "currency",
        "total_amount",
    }
