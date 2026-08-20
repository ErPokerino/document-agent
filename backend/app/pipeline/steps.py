import base64

import pymupdf

from app.domain.models import PromptConfiguration
from app.pipeline.engine import PipelineContext
from app.services.lm_studio import LMStudioClient


# Rendered pages are held in memory as base64 strings until the model call
# returns. Without a ceiling, a 100-page limit on a large PDF can exhaust the
# backend process long before LM Studio ever rejects the request.
MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024


class InspectPdf:
    def __init__(
        self,
        max_pages_to_analyze: int = 10,
        max_pages: int | None = None,
        page_limit: int | None = None,
    ) -> None:
        self.max_pages_to_analyze = max_pages_to_analyze
        self.max_pages = max_pages
        # Explicit override used by isolated pipeline tests.
        self.page_limit = page_limit

    async def run(self, context: PipelineContext) -> None:
        try:
            document = pymupdf.open(stream=context.content, filetype="pdf")
        except Exception as exc:
            raise ValueError("The file is not a valid PDF") from exc

        try:
            page_count = document.page_count
        finally:
            document.close()

        if page_count == 0:
            raise ValueError("The PDF contains no pages")
        if self.max_pages is not None and page_count > self.max_pages:
            raise ValueError(f"The POC supports at most {self.max_pages} pages")

        page_limit = self.page_limit or self.max_pages_to_analyze
        processed_pages = min(page_count, page_limit)
        context.artifacts.update(
            {
                "page_count": page_count,
                "page_limit": page_limit,
                "processed_pages": processed_pages,
                "first_processed_page": 1,
                "last_processed_page": processed_pages,
                "cut_applied": page_count > processed_pages,
                "configured_page_limit": self.max_pages_to_analyze,
            }
        )


class ExtractConfiguredEntities:
    def __init__(self, prompts: PromptConfiguration, scale: float = 1.35) -> None:
        self.prompts = prompts
        self.scale = scale

    async def run(self, context: PipelineContext) -> None:
        page_count: int = context.artifacts["page_count"]
        processed_pages: int = context.artifacts["processed_pages"]
        images: list[str] = []

        document = pymupdf.open(stream=context.content, filetype="pdf")
        matrix = pymupdf.Matrix(self.scale, self.scale)
        rendered_bytes = 0
        try:
            for page_index in range(processed_pages):
                pixmap = document[page_index].get_pixmap(matrix=matrix, alpha=False)
                encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
                del pixmap
                rendered_bytes += len(encoded)
                if rendered_bytes > MAX_TOTAL_IMAGE_BYTES:
                    budget_mb = MAX_TOTAL_IMAGE_BYTES // (1024 * 1024)
                    raise ValueError(
                        f"Rendering page {page_index + 1} exceeded the {budget_mb} MB image "
                        f"budget for a single request. Lower 'Maximum pages per extraction' "
                        f"in Settings and try again."
                    )
                images.append(encoded)
        finally:
            document.close()

        client = LMStudioClient(context.lm_studio_url)
        page_range = "1" if processed_pages == 1 else f"1-{processed_pages}"
        context.artifacts["extraction"] = await client.extract_entities(
            context.model,
            images,
            self.prompts,
            page_range,
            total_pages=page_count,
            processed_pages=processed_pages,
        )
        context.artifacts["inference_stats"] = getattr(client, "last_prediction_stats", None) or {}
