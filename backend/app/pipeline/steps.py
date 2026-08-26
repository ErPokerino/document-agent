import base64

import pymupdf

from app.domain.models import EntityDefinition, FieldExtraction, PromptConfiguration
from app.pipeline.engine import PipelineContext
from app.pipeline.regex_refine import apply_rules
from app.services.document_ai import (
    DocumentAiClient,
    DocumentAiError,
    markdown_from_layout,
    text_from_ocr,
)
from app.services.gemini import GeminiClient
from app.services.master_data import MasterDataStore
from app.services.similarity import DEFAULT_ALGORITHM, similarity
from app.services.supplier_rules import (
    SupplierRule,
    apply_deterministic_rules,
    prompted_rules,
    rules_for,
)
from app.services.custom_extractor import (
    API_VERSION as CUSTOM_EXTRACTOR_API_VERSION,
    validated_entities_from_response,
    locations_from_response,
    schema_override,
)
from app.services.text_boxes import tokens_from_ocr
from app.services.lm_studio import LMStudioClient


# Rendered pages are held in memory as base64 strings until the model call
# returns. Without a ceiling, a 100-page limit on a large PDF can exhaust the
# backend process long before LM Studio ever rejects the request.
MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024


def build_extraction_client(context: PipelineContext):
    """The pipeline is provider-agnostic; only this decides who does the work."""
    if context.provider == "gemini":
        return GeminiClient(context.gemini_api_key, context.gemini_thinking_level)
    return LMStudioClient(context.lm_studio_url)


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


class RenderPages:
    """Turn the pages the inspection selected into base64 PNGs.

    Separate from extraction on purpose: an OCR or layout step produces text
    from the same PDF, and the extraction step should not care which arrived.
    """

    def __init__(self, scale: float = 1.35) -> None:
        self.scale = scale

    async def run(self, context: PipelineContext) -> None:
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
                        f"budget for a single request. The budget covers every page this "
                        f"pipeline renders, so it is reached sooner the higher the page "
                        f"limit is set."
                    )
                images.append(encoded)
        finally:
            document.close()

        context.artifacts["images"] = images


class ExtractEntities:
    """Ask the configured provider for the entities, from images or from text."""

    def __init__(self, prompts: PromptConfiguration) -> None:
        self.prompts = prompts

    async def run(self, context: PipelineContext) -> None:
        page_count: int = context.artifacts["page_count"]
        processed_pages: int = context.artifacts["processed_pages"]
        images: list[str] = context.artifacts.get("images") or []
        document_text: str = context.artifacts.get("text") or ""

        client = build_extraction_client(context)
        page_range = "1" if processed_pages == 1 else f"1-{processed_pages}"
        context.artifacts["extraction"] = await client.extract_entities(
            context.model,
            images,
            self.prompts,
            page_range,
            total_pages=page_count,
            processed_pages=processed_pages,
            document_text=document_text,
        )
        context.artifacts["inference_stats"] = getattr(client, "last_prediction_stats", None) or {}


class RefineWithRegex:
    """Apply the user's per-field rules to whatever the model returned."""

    def __init__(self, entities, rules) -> None:
        self.entities = entities
        self.rules = rules

    async def run(self, context: PipelineContext) -> None:
        extraction = context.artifacts.get("extraction")
        if not extraction:
            return
        context.artifacts["extraction"] = apply_rules(
            self.entities, extraction, self.rules, context.artifacts.get("text")
        )


class ExtractConfiguredEntities:
    """Render and extract in one step.

    Kept for the tests that predate the split and for any caller that just wants
    the old behaviour; a pipeline uses RenderPages and ExtractEntities instead.
    """

    def __init__(self, prompts: PromptConfiguration, scale: float = 1.35) -> None:
        self.render = RenderPages(scale)
        self.extract = ExtractEntities(prompts)
        self.prompts = prompts
        self.scale = scale

    async def run(self, context: PipelineContext) -> None:
        await self.render.run(context)
        await self.extract.run(context)


class ReadWithDocumentAi:
    """Have Google read the document, and leave what it read behind.

    Both processors are the same request with a different id, so they are the
    same step: OCR leaves plain text, the Layout Parser leaves markdown that
    keeps the headings and tables, plus the raw structure for anything later.
    """

    def __init__(self, kind: str, processor_id: str, feeds_model: bool = True) -> None:
        self.kind = kind
        self.processor_id = processor_id
        # An OCR step can be in a pipeline purely to supply the boxes that
        # highlight a value on the page, while a multimodal model reads the
        # picture and never sees this text. Handing the model text it was not
        # meant to have would quietly change what it extracts.
        self.feeds_model = feeds_model

    def _client(self, context: PipelineContext) -> DocumentAiClient:
        return DocumentAiClient(
            context.gcp_credentials_path, context.gcp_project_id, context.gcp_location
        )

    async def run(self, context: PipelineContext) -> None:
        if not self.processor_id.strip():
            raise DocumentAiError(
                f"No processor id is configured for {self.kind.replace('_', ' ')}. "
                "Add it in Settings."
            )
        processed_pages: int = context.artifacts["processed_pages"]
        # Document AI charges per page, so the pipeline's page limit has to be
        # applied before the document leaves this machine, not after.
        content = _first_pages(context.content, processed_pages)

        answer = await self._client(context).process(self.processor_id, content)
        document = answer.get("document") or {}

        if self.kind == "document_ai_layout":
            layout = document.get("documentLayout") or {}
            context.artifacts["layout"] = layout
            if self.feeds_model:
                context.artifacts["text"] = markdown_from_layout(layout)
        else:
            # Kept whether or not the model is shown the text: this is what
            # locates an extracted value on the page afterwards.
            context.artifacts["ocr_tokens"] = tokens_from_ocr(document)
            if self.feeds_model:
                context.artifacts["text"] = text_from_ocr(document)

        counted = dict(context.artifacts.get("document_ai_pages") or {})
        counted[self.kind] = counted.get(self.kind, 0) + processed_pages
        context.artifacts["document_ai_pages"] = counted


def _first_pages(content: bytes, pages: int) -> bytes:
    """A copy of the PDF holding only the first `pages` pages."""
    source = pymupdf.open(stream=content, filetype="pdf")
    try:
        if pages >= source.page_count:
            return content
        trimmed = pymupdf.open()
        try:
            trimmed.insert_pdf(source, from_page=0, to_page=pages - 1)
            return trimmed.tobytes()
        finally:
            trimmed.close()
    finally:
        source.close()


# What a similarity score means in the three words the rest of the app speaks.
# A match below the pipeline's threshold never gets here: it is refused.
HIGH_SIMILARITY = 0.95
MEDIUM_SIMILARITY = 0.8


def confidence_from_similarity(score: float) -> str:
    if score >= HIGH_SIMILARITY:
        return "high"
    if score >= MEDIUM_SIMILARITY:
        return "medium"
    return "low"


class LookUpInMasterData:
    """Fill an entity the document never carried, from the supplier register.

    The document says "UL VS LTD"; what handles it downstream needs the
    internal id, which is on no page. This compares the extracted name with
    every name in the register and takes the best, provided it is close enough
    to be worth trusting — how close is the pipeline's decision, not ours.
    """

    def __init__(
        self,
        *,
        entities: list[EntityDefinition],
        master_data: MasterDataStore,
        table: str,
        source_entity: str,
        target_entity: str,
        algorithm: str = DEFAULT_ALGORITHM,
        minimum_similarity: float = 0.75,
    ) -> None:
        self.entities = entities
        self.master_data = master_data
        self.table = table
        self.source_entity = source_entity
        self.target_entity = target_entity
        self.algorithm = algorithm
        self.minimum_similarity = minimum_similarity

    def _refused(self, warning: str) -> FieldExtraction:
        return FieldExtraction(value=None, confidence="low", warning=warning)

    async def run(self, context: PipelineContext) -> None:
        extraction: dict[str, FieldExtraction] = dict(context.artifacts.get("extraction") or {})
        source = extraction.get(self.source_entity)
        name = "" if source is None or source.value is None else str(source.value).strip()

        if not name:
            extraction[self.target_entity] = self._refused(
                f"No {self.source_entity} was extracted, so there was nothing to look up."
            )
            context.artifacts["extraction"] = extraction
            return

        definition = self.master_data.table(self.table)
        register = self.master_data.rows(self.table)
        if not register:
            extraction[self.target_entity] = self._refused(
                f"The {definition.label} table is empty. Add rows in Master Data."
            )
            context.artifacts["extraction"] = extraction
            return

        column = definition.match_column
        scored = ((row, similarity(name, row.get(column), self.algorithm)) for row in register)
        best, score = max(scored, key=lambda pair: pair[1])
        score = round(score, 4)

        if score < self.minimum_similarity:
            extraction[self.target_entity] = self._refused(
                f"No row in {definition.label} is close enough to {name!r}: the best match "
                f"scored {score:.2f}, below the {self.minimum_similarity:.2f} this pipeline asks for."
            )
        else:
            extraction[self.target_entity] = FieldExtraction(
                value=best[definition.id_column],
                confidence=confidence_from_similarity(score),
                score=score,
                warning=None,
            )
        context.artifacts["extraction"] = extraction


class MarkUnfilledDerivedEntities:
    """Say, in the result, which derived fields this pipeline never produces.

    Leaving them out would read as "the model returned nothing", which is not
    what happened: nothing here was asked to produce them. Every run then
    carries the same set of fields, which is what makes two runs comparable.
    """

    def __init__(self, names: list[str]) -> None:
        self.names = names

    async def run(self, context: PipelineContext) -> None:
        extraction: dict[str, FieldExtraction] = dict(context.artifacts.get("extraction") or {})
        for name in self.names:
            if name in extraction:
                continue
            extraction[name] = FieldExtraction(
                value=None,
                confidence="low",
                warning=f"No step in this pipeline fills '{name}'.",
            )
        context.artifacts["extraction"] = extraction


class ApplySupplierRules:
    """Corrections written for the supplier this document turned out to be from.

    Runs after the register lookup, because it keys on `id_subject`: several
    spellings of one supplier resolve to the same internal id, and the id is
    what is either right or wrong.

    Deterministic rules run first and cost nothing. A prompted rule is a second
    model call, so one is made only when there is a prompted rule to make it
    for, and it asks about those fields alone rather than re-extracting the
    document.
    """

    def __init__(
        self,
        rules: list[SupplierRule],
        prompts: PromptConfiguration,
        source_entity: str = "id_subject",
    ) -> None:
        self.rules = rules
        self.prompts = prompts
        self.source_entity = source_entity

    async def run(self, context: PipelineContext) -> None:
        extraction: dict[str, FieldExtraction] = context.artifacts.get("extraction") or {}
        identity = extraction.get(self.source_entity)
        applicable = rules_for(self.rules, getattr(identity, "value", None))
        if not applicable:
            return

        document_text: str = context.artifacts.get("text") or ""
        updated, changed = apply_deterministic_rules(extraction, applicable, document_text)

        asked = prompted_rules(applicable)
        wanted = [rule.entity for rule in asked if rule.entity in updated]
        if wanted:
            updated, reasked = await self._ask_again(context, updated, asked, wanted)
            changed = changed + [entity for entity in reasked if entity not in changed]

        context.artifacts["extraction"] = updated
        context.artifacts["supplier_rules_applied"] = changed

    async def _ask_again(
        self,
        context: PipelineContext,
        extraction: dict[str, FieldExtraction],
        asked: list[SupplierRule],
        wanted: list[str],
    ) -> tuple[dict[str, FieldExtraction], list[str]]:
        """One more call, about the named fields only.

        Re-extracting the whole document would risk the fields that were
        already right; the point of a supplier rule is that it knows something
        extra about a few of them.
        """
        subset = [entity for entity in self.prompts.entities if entity.name in wanted]
        if not subset:
            return extraction, []

        instructions = "\n".join(
            f"- {rule.entity}: {rule.prompt.strip()}" for rule in asked if rule.prompt.strip()
        )
        focused = self.prompts.model_copy(
            update={
                "entities": subset,
                "user_prompt": (
                    f"{self.prompts.user_prompt.strip()}\n\n"
                    f"This document is from a supplier with known conventions. "
                    f"Apply these instructions, which override anything above:\n{instructions}"
                ),
            }
        )

        client = build_extraction_client(context)
        processed_pages: int = context.artifacts["processed_pages"]
        answer = await client.extract_entities(
            context.model,
            context.artifacts.get("images") or [],
            focused,
            "1" if processed_pages == 1 else f"1-{processed_pages}",
            total_pages=context.artifacts["page_count"],
            processed_pages=processed_pages,
            document_text=context.artifacts.get("text") or "",
        )

        result = dict(extraction)
        changed: list[str] = []
        for entity in wanted:
            replacement = answer.get(entity)
            if replacement is None or replacement.value == result[entity].value:
                continue
            result[entity] = replacement
            changed.append(entity)
        return result, changed


class ExtractWithCustomExtractor:
    """Read the configured fields with a Google Custom Extractor.

    Replaces the model call rather than feeding it: the processor returns the
    values, its own confidence for each, and the box each one sits in. Nothing
    here asks anything how sure it is.

    The fields travel with the request as a schema override, so Extraction
    stays the one place they are defined and the processor is never edited to
    match it.
    """

    def __init__(self, processor_id: str, entities: list[EntityDefinition]) -> None:
        self.processor_id = processor_id
        self.entities = entities

    async def run(self, context: PipelineContext) -> None:
        if not self.processor_id.strip():
            raise DocumentAiError(
                "No Custom Extractor processor id is configured. Add it in Settings."
            )
        processed_pages: int = context.artifacts["processed_pages"]

        client = DocumentAiClient(
            context.gcp_credentials_path, context.gcp_project_id, context.gcp_location
        )
        answer = await client.process(
            self.processor_id,
            context.content,
            process_options={
                "schemaOverride": schema_override(self.entities),
                # The pipeline's page limit, asked of the API rather than
                # applied by rewriting the PDF here. Both bill the same pages,
                # and the processor read a rewritten page slightly worse — it
                # truncated a supplier name that it read in full from the
                # original.
                "individualPageSelector": {
                    "pages": list(range(1, processed_pages + 1))
                },
            },
            version=CUSTOM_EXTRACTOR_API_VERSION,
        )
        document = answer.get("document") or {}

        context.artifacts["extraction"] = validated_entities_from_response(document, self.entities)
        # The processor placed every value it found, so nothing has to be
        # searched for in the page text afterwards.
        context.artifacts["field_locations"] = [
            {
                "entity": located.entity,
                "page": located.page,
                "left": located.left,
                "top": located.top,
                "right": located.right,
                "bottom": located.bottom,
            }
            for located in locations_from_response(document, self.entities)
        ]
        # It reads the page as well as extracting from it, so the tokens are
        # there for anything that wants to locate a value it did not return.
        context.artifacts["ocr_tokens"] = tokens_from_ocr(document)
        context.artifacts["text"] = text_from_ocr(document)

        counted = dict(context.artifacts.get("document_ai_pages") or {})
        counted["document_ai_extract"] = counted.get("document_ai_extract", 0) + processed_pages
        context.artifacts["document_ai_pages"] = counted
