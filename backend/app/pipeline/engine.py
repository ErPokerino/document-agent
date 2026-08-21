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
    artifacts: dict[str, Any] = field(default_factory=dict)


class PipelineStep(Protocol):
    async def run(self, context: PipelineContext) -> None: ...


class DocumentPipeline:
    """Small orchestration core designed for future classification and validation steps."""

    def __init__(self, steps: list[PipelineStep]) -> None:
        self.steps = steps

    async def run(self, context: PipelineContext) -> PipelineContext:
        for step in self.steps:
            await step.run(context)
        return context
