import asyncio
import base64
from typing import Any

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
from app.services.extraction_provider import ExtractionProvider
from app.services.field_validation import normalize_field
from app.services.gemini import GeminiClient
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
from app.services.reading_cache import reading_key
from app.services.text_boxes import Box, TextToken, tokens_from_ocr
from app.services.lm_studio import LMStudioClient


# Rendered pages are held in memory as base64 strings until the model call
# returns. Without a ceiling, a 100-page limit on a large PDF can exhaust the
# backend process long before LM Studio ever rejects the request.
MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024


def build_extraction_client(context: PipelineContext) -> ExtractionProvider:
    """The pipeline is provider-agnostic; only this decides who does the work."""
    if context.provider == "gemini":
        return GeminiClient(context.gemini_api_key, context.gemini_thinking_level)
    return LMStudioClient(context.lm_studio_url)


def _page_count(content: bytes) -> int:
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError("The file is not a valid PDF") from exc
    try:
        return document.page_count
    finally:
        document.close()


class InspectPdf:
    """Count the pages and decide which of them the pipeline may process.

    The pipeline's page limit is the only cut. A PDF longer than it is still
    accepted, and the pages beyond the limit are reported as not processed.
    """

    def __init__(self, page_limit: int = 10) -> None:
        self.page_limit = page_limit

    async def run(self, context: PipelineContext) -> None:
        # pymupdf blocks. On the event loop, a large PDF would stall health,
        # cancel and every other request until it was done.
        page_count = await asyncio.to_thread(_page_count, context.content)
        if page_count == 0:
            raise ValueError("The PDF contains no pages")

        page_limit = self.page_limit
        processed_pages = min(page_count, page_limit)
        context.artifacts.update(
            {
                "page_count": page_count,
                "page_limit": page_limit,
                "processed_pages": processed_pages,
                "first_processed_page": 1,
                "last_processed_page": processed_pages,
                "cut_applied": page_count > processed_pages,
                "configured_page_limit": page_limit,
            }
        )


def render_page_png(content: bytes, page: int, scale: float) -> bytes | None:
    """One page as a PNG, or None when the document has no such page."""
    document = pymupdf.open(stream=content, filetype="pdf")
    try:
        if page < 0 or page >= document.page_count:
            return None
        pixmap = document[page].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()


def _render_pages(content: bytes, pages: int, scale: float) -> list[str]:
    images: list[str] = []
    document = pymupdf.open(stream=content, filetype="pdf")
    matrix = pymupdf.Matrix(scale, scale)
    rendered_bytes = 0
    try:
        for page_index in range(pages):
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
    return images


class RenderPages:
    """Turn the pages the inspection selected into base64 PNGs.

    Separate from extraction on purpose: an OCR or layout step produces text
    from the same PDF, and the extraction step should not care which arrived.
    """

    def __init__(self, scale: float = 1.35) -> None:
        self.scale = scale

    async def run(self, context: PipelineContext) -> None:
        processed_pages: int = context.artifacts["processed_pages"]
        context.artifacts["images"] = await asyncio.to_thread(
            _render_pages, context.content, processed_pages, self.scale
        )


def _native_text(content: bytes, pages: int) -> tuple[list[str], list[TextToken]]:
    """Each page's embedded text, and every word on it with a normalized box."""
    document = pymupdf.open(stream=content, filetype="pdf")
    texts: list[str] = []
    tokens: list[TextToken] = []
    try:
        for index in range(pages):
            page = document[index]
            texts.append(page.get_text("text").strip())
            # Word boxes are in unrotated page space; the rendered page and the
            # highlight are not, so each box is turned with the page first.
            width, height = page.rect.width or 1, page.rect.height or 1
            for x0, y0, x1, y1, word, *_ in page.get_text("words"):
                if not word.strip():
                    continue
                rect = pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix
                tokens.append(
                    TextToken(
                        text=word,
                        page=index,
                        box=Box(
                            left=max(0.0, rect.x0 / width),
                            top=max(0.0, rect.y0 / height),
                            right=min(1.0, rect.x1 / width),
                            bottom=min(1.0, rect.y1 / height),
                        ),
                    )
                )
    finally:
        document.close()
    return texts, tokens


class ReadPdfText:
    """Read the text a native PDF carries, without sending it anywhere.

    Most invoices are generated rather than scanned, and their text is already
    in the file: reading it costs nothing, takes milliseconds and never leaves
    the machine. A scan carries none, and an empty reading passed on as a
    successful one would have a model answer from nothing — so a document with
    no text on any page it may read is refused, and a page without text is
    named in the text the model is given.

    Native text is not automatically right. Reading order, stale embedded OCR
    and tables can all differ from what the page shows, which is why this is a
    reader to measure in Lab against OCR, not a default.

    When the pipeline has an OCR step set to read what this step could not,
    the refusal is that step's to replace: the document is marked as carrying
    no text and passed on with nothing read, rather than refused.
    """

    def __init__(self, feeds_model: bool = True, ocr_follows: bool = False) -> None:
        # As with OCR: a reading can be there only to locate values on the page
        # while a vision model reads the picture.
        self.feeds_model = feeds_model
        self.ocr_follows = ocr_follows

    async def run(self, context: PipelineContext) -> None:
        processed_pages: int = context.artifacts["processed_pages"]
        texts, tokens = await asyncio.to_thread(_native_text, context.content, processed_pages)
        context.artifacts["pdf_text_pages"] = [
            {"page": index + 1, "characters": len(text)} for index, text in enumerate(texts)
        ]
        empty = [index + 1 for index, text in enumerate(texts) if not text]
        if len(empty) == len(texts):
            if self.ocr_follows:
                context.artifacts["pdf_text_missing"] = True
                return
            span = "page 1" if processed_pages == 1 else f"pages 1–{processed_pages}"
            raise ValueError(
                f"The PDF carries no text of its own on {span}, which is what a scanned "
                "document looks like."
            )

        context.artifacts["ocr_tokens"] = tokens
        reading = "\n\n".join(
            f"[Page {index + 1}]\n{text}" if text else f"[Page {index + 1} carries no embedded text.]"
            for index, text in enumerate(texts)
        )
        # What was read, whether or not the model is shown it: a step that
        # predicts from the text of the document needs it either way.
        context.artifacts["document_text"] = reading
        if self.feeds_model:
            context.artifacts["text"] = reading


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
        if context.provider == "gemini" and any(
            context.artifacts["inference_stats"].get(key) is None
            for key in ("prompt_tokens", "completion_tokens")
        ):
            context.artifacts["usage_complete"] = False


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

    def __init__(self, kind: str, processor_id: str, feeds_model: bool = True, project_id: str | None = None, location: str | None = None, only_without_pdf_text: bool = False) -> None:
        self.kind = kind
        self.processor_id = processor_id
        self.project_id = project_id
        self.location = location
        # An OCR step can be in a pipeline purely to supply the boxes that
        # highlight a value on the page, while a multimodal model reads the
        # picture and never sees this text. Handing the model text it was not
        # meant to have would quietly change what it extracts.
        self.feeds_model = feeds_model
        # Set, the step reads only a document Read PDF text found no text on;
        # every other document is neither uploaded nor billed.
        self.only_without_pdf_text = only_without_pdf_text

    def _client(self, context: PipelineContext) -> DocumentAiClient:
        return DocumentAiClient(
            context.gcp_credentials_path, self.project_id or context.gcp_project_id, self.location or context.gcp_location
        )

    async def run(self, context: PipelineContext) -> None:
        if self.only_without_pdf_text and not context.artifacts.get("pdf_text_missing"):
            return
        if not self.processor_id.strip():
            raise DocumentAiError(
                f"No processor id is configured for {self.kind.replace('_', ' ')}. "
                "Select it in Pipelines from the Processors catalog."
            )
        processed_pages: int = context.artifacts["processed_pages"]
        # Document AI charges per page, so the pipeline's page limit has to be
        # applied before the document leaves this machine, not after.
        content = await asyncio.to_thread(_first_pages, context.content, processed_pages)

        cache = context.reading_cache
        key = (
            reading_key(
                kind=self.kind,
                project_id=self.project_id or context.gcp_project_id,
                location=self.location or context.gcp_location,
                processor_id=self.processor_id,
                api_version="v1",
                content=context.content,
                pages=processed_pages,
            )
            if cache is not None
            else None
        )
        answer = await asyncio.to_thread(cache.get, key) if key and context.reuse_readings else None
        reused = answer is not None
        if answer is None:
            answer = await self._client(context).process(self.processor_id, content)
            if key:
                await asyncio.to_thread(cache.put, key, answer)
        document = answer.get("document") or {}

        if self.kind == "document_ai_layout":
            layout = document.get("documentLayout") or {}
            context.artifacts["layout"] = layout
            if self.feeds_model:
                context.artifacts["text"] = markdown_from_layout(layout)
            context.artifacts["document_text"] = markdown_from_layout(layout)
        else:
            # Kept whether or not the model is shown the text: this is what
            # locates an extracted value on the page afterwards.
            context.artifacts["ocr_tokens"] = tokens_from_ocr(document)
            if self.feeds_model:
                context.artifacts["text"] = text_from_ocr(document)
            context.artifacts["document_text"] = text_from_ocr(document)

        # A reused reading was neither sent nor billed, and saying it was
        # would put a page on the run's bill that Google never charged.
        tally = "cached_pages" if reused else "document_ai_pages"
        counted = dict(context.artifacts.get(tally) or {})
        counted[self.kind] = counted.get(self.kind, 0) + processed_pages
        context.artifacts[tally] = counted


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
        # A MasterDataStore, or the frozen rows a Lab run recorded. Both
        # answer table() and rows(); the step does not write.
        master_data: Any,
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


# What a TF-IDF cosine similarity is called in the three words the rest of the
# app speaks. A display convention, not a calibration: nothing has measured
# where these bands fall on real documents, so a threshold belongs on the score
# itself, which the Lab's coverage curve sets against accuracy.
KNN_HIGH = 0.8
KNN_MEDIUM = 0.5


class PredictWithArtifact:
    """Fill fields with a model trained on labelled datasets.

    It reads the text a reading step left, whether or not a model is shown
    that text, and never leaves the machine.
    """

    kind = "artifact_predict"

    def __init__(
        self,
        *,
        model: Any,
        entities: list[EntityDefinition],
        minimum_similarity: float,
        artifact_id: str,
        artifact_name: str,
    ) -> None:
        self.model = model
        self.entities = entities
        self.minimum_similarity = minimum_similarity
        self.artifact_id = artifact_id
        self.artifact_name = artifact_name

    async def run(self, context: PipelineContext) -> None:
        extraction: dict[str, FieldExtraction] = dict(context.artifacts.get("extraction") or {})
        text = str(context.artifacts.get("document_text") or context.artifacts.get("text") or "")
        if not text.strip():
            for entity in self.entities:
                extraction[entity.name] = FieldExtraction(
                    value=None, confidence="low",
                    warning="No text was read from this document, so there was nothing to compare.",
                )
            context.artifacts["extraction"] = extraction
            return

        predictions = await asyncio.to_thread(self.model.predict_all, text, [entity.name for entity in self.entities])
        for entity in self.entities:
            extraction[entity.name] = self._field(entity, predictions.get(entity.name))
        context.artifacts["extraction"] = extraction

    def _field(self, entity: EntityDefinition, prediction: Any) -> FieldExtraction:
        if prediction is None:
            return FieldExtraction(
                value=None, confidence="low",
                warning=f"No document the model learned from is labelled for '{entity.name}'.",
            )
        nearest = f"{prediction.nearest.dataset}/{prediction.nearest.document}" if prediction.nearest else "a training document"
        evidence = (
            f"{self.artifact_name}: nearest {nearest}, similarity {prediction.score:.2f}"
            + (f", {round(prediction.agreement * 100)}% of the vote" if self.model.parameters.k > 1 else "")
        )
        if prediction.score < self.minimum_similarity:
            return FieldExtraction(
                value=None, confidence="low", score=prediction.score, evidence=evidence,
                warning=(
                    f"The nearest labelled document ({nearest}) is {prediction.score:.2f} similar, "
                    f"below the {self.minimum_similarity:.2f} this pipeline asks for."
                ),
            )
        if prediction.value is None:
            return FieldExtraction(value=None, confidence="low", score=prediction.score, evidence=evidence)
        confidence = "high" if prediction.score >= KNN_HIGH else "medium" if prediction.score >= KNN_MEDIUM else "low"
        try:
            field = normalize_field({"value": prediction.value, "confidence": confidence}, entity)
        except ValueError as exc:
            return FieldExtraction(
                value=None, confidence="low", score=prediction.score, evidence=evidence,
                warning=f"The label {prediction.value!r} of {nearest} was discarded: {exc}.",
            )
        return field.model_copy(update={"score": prediction.score, "evidence": evidence})


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

        # A supplier exception is an additional paid call, not a replacement
        # for the extraction whose counters are already in the context.
        previous = dict(context.artifacts.get("inference_stats") or {})
        extra = getattr(client, "last_prediction_stats", None) or {}
        if context.provider == "gemini" and any(extra.get(key) is None for key in ("prompt_tokens", "completion_tokens")):
            context.artifacts["usage_complete"] = False
        for key in ("prompt_tokens", "completion_tokens"):
            if key in extra:
                previous[key] = (previous.get(key) or 0) + (extra.get(key) or 0)
        context.artifacts["inference_stats"] = previous

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

    def __init__(self, processor_id: str, entities: list[EntityDefinition], project_id: str | None = None, location: str | None = None) -> None:
        self.processor_id = processor_id
        self.project_id = project_id
        self.location = location
        self.entities = entities

    async def run(self, context: PipelineContext) -> None:
        if not self.processor_id.strip():
            raise DocumentAiError(
                "No Custom Extractor processor id is configured. Select it in Pipelines from the Processors catalog."
            )
        processed_pages: int = context.artifacts["processed_pages"]

        client = DocumentAiClient(
            context.gcp_credentials_path, self.project_id or context.gcp_project_id, self.location or context.gcp_location
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
        context.artifacts["document_text"] = context.artifacts["text"]

        counted = dict(context.artifacts.get("document_ai_pages") or {})
        counted["document_ai_extract"] = counted.get("document_ai_extract", 0) + processed_pages
        context.artifacts["document_ai_pages"] = counted
