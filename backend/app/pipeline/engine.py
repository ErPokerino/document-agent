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
    "ResolveCandidates": "resolve_candidates",
}


def step_name(step: object) -> str:
    kind = getattr(step, "kind", None)
    if isinstance(kind, str) and kind:
        return kind
    return _STEP_NAMES.get(type(step).__name__, type(step).__name__)


def method_name(step: object) -> str:
    """What a step is called as the author of a candidate."""
    named = getattr(step, "method", None)
    return named if isinstance(named, str) and named else step_name(step)


def method_names(steps: list[object]) -> list[str]:
    """One name per step, numbered when a pipeline repeats a kind."""
    names = [method_name(step) for step in steps]
    seen: dict[str, int] = {}
    unique = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        unique.append(name if names.count(name) == 1 else f"{name} #{seen[name]}")
    return unique


def record_candidates(before: dict[str, Any], after: dict[str, Any], method: str) -> dict[str, Any]:
    """Add a candidate for every field the step wrote.

    A field a step left alone is the same object afterwards; one it wrote is a
    new object, even when the value is the same. That distinction is the one
    that matters: a second method agreeing with the first is evidence, and
    comparing values would hide it.
    """
    from app.domain.models import FieldCandidate

    recorded = dict(after)
    for name, field in after.items():
        previous = before.get(name)
        if field is previous or not hasattr(field, "candidates"):
            continue
        history = list(getattr(previous, "candidates", None) or [])
        candidate = FieldCandidate(
            method=method,
            value=field.value,
            confidence=field.confidence,
            score=field.score,
            warning=field.warning,
            evidence=field.evidence,
        )
        recorded[name] = field.model_copy(update={"candidates": [*history, candidate]})
    return recorded


class DocumentPipeline:
    """Small orchestration core designed for future classification and validation steps."""

    def __init__(self, steps: list[PipelineStep]) -> None:
        self.steps = steps
        self.methods = method_names(steps)

    async def run(
        self,
        context: PipelineContext,
        on_step: Callable[[object], None] | None = None,
    ) -> PipelineContext:
        for step, method in zip(self.steps, self.methods):
            # Reported before the step runs, so a poll during a long call
            # names the step that is actually in flight.
            if on_step is not None:
                on_step(step)
            before = dict(context.artifacts.get("extraction") or {})
            await step.run(context)
            after = context.artifacts.get("extraction")
            # A step that only chooses among candidates, or only states that a
            # field is empty, proposes nothing of its own.
            if after and getattr(step, "proposes", True):
                context.artifacts["extraction"] = record_candidates(before, after, method)
        return context
