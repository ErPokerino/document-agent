from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class PipelineContext:
    filename: str
    content: bytes
    model: str
    lm_studio_url: str
    provider: str = "lm_studio"
    gemini_api_key: str = ""
    gemini_thinking_level: str = "low"
    gcp_credentials_path: str = ""
    gcp_project_id: str = ""
    gcp_location: str = "eu"
    # Where pinned Document AI readings are kept. Every reading is written to
    # it; one is read back only when the run chose to reuse readings, since a
    # reused reading costs neither the time nor the pages the pipeline costs.
    reading_cache: Any = None
    reuse_readings: bool = False
    artifacts: dict[str, Any] = field(default_factory=dict)


class PipelineStep(Protocol):
    async def run(self, context: PipelineContext) -> None: ...


# Steps compiled before `kind` was stored on the instance still need a name
# the UI can show. The class is the only remaining evidence.
_STEP_NAMES = {
    "InspectPdf": "inspect_pdf",
    "RenderPages": "render_pages",
    "ReadPdfText": "read_pdf_text",
    "ExtractEntities": "llm_extract",
    "RefineWithRegex": "regex_refine",
    "LookUpInMasterData": "master_data_lookup",
    "ApplySupplierRules": "supplier_rules",
    "ExtractWithCustomExtractor": "document_ai_extract",
    "MarkUnfilledDerivedEntities": "mark_unfilled",
}


def step_name(step: object) -> str:
    kind = getattr(step, "kind", None)
    if isinstance(kind, str) and kind:
        return kind
    return _STEP_NAMES.get(type(step).__name__, type(step).__name__)


class DocumentPipeline:
    """Small orchestration core designed for future classification and validation steps."""

    def __init__(self, steps: list[PipelineStep]) -> None:
        self.steps = steps

    async def run(
        self,
        context: PipelineContext,
        on_step: Callable[[object], None] | None = None,
    ) -> PipelineContext:
        for step in self.steps:
            # Reported before the step runs, so a poll during a long call
            # names the step that is actually in flight.
            if on_step is not None:
                on_step(step)
            await step.run(context)
        return context
