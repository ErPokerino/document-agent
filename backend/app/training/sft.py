"""Labelled documents as supervised fine-tuning examples, asked exactly as DocuFlow asks.

A tuned model learns the question it was trained on. If the examples were
worded differently from the request DocuFlow sends at run time, the tuning
would teach a prompt nobody sends — so each example is built by the same code
that builds Gemini's request: the system instruction with the entity lines and
the confidence rubric, and the user text with the page note and the document
text. The answer is the JSON Gemini is asked to return, written from the labels.

Examples carry text only: the document as the pipeline's reading steps read
it. A model tuned on them is served by a pipeline that reads text the same way.

A document is left out when a field the model is asked for is not labelled.
Writing null in its place would teach the model to answer nothing where the
document may well say something.
"""

import json
from typing import Any, Literal

from app.domain.models import PromptConfiguration, model_entities
from app.services.extraction_provider import ExtractionProvider
from app.services.gemini import GeminiClient

Format = Literal["vertex_gemini", "openai_chat"]
FORMATS: dict[str, str] = {
    "vertex_gemini": "Gemini on Vertex AI: systemInstruction and user/model contents",
    "openai_chat": "Chat messages: system, user and assistant",
}


def answer(prompts: PromptConfiguration, labels: dict[str, Any]) -> str:
    """The JSON Gemini is asked for, from ground truth. A labelled value is certain."""
    entities = model_entities(prompts.entities)
    missing = [entity.name for entity in entities if entity.name not in labels]
    if missing:
        raise ValueError(f"not labelled for: {', '.join(missing)}")
    body: dict[str, Any] = {entity.name: labels[entity.name] for entity in entities}
    body["confidence"] = {entity.name: "high" if labels[entity.name] is not None else "low" for entity in entities}
    return json.dumps(body, ensure_ascii=False)


def example(
    format: Format,
    prompts: PromptConfiguration,
    labels: dict[str, Any],
    text: str,
    *,
    total_pages: int,
    processed_pages: int,
) -> dict[str, Any]:
    target = answer(prompts, labels)
    page_range = "1" if processed_pages == 1 else f"1-{processed_pages}"
    system = GeminiClient._system_prompt(prompts)
    user = ExtractionProvider._user_text(
        prompts, page_range, total_pages=total_pages, processed_pages=processed_pages, document_text=text,
    )
    if format == "openai_chat":
        return {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": target},
            ]
        }
    return {
        "systemInstruction": {"role": "system", "parts": [{"text": system}]},
        "contents": [
            {"role": "user", "parts": [{"text": user}]},
            {"role": "model", "parts": [{"text": target}]},
        ],
    }
