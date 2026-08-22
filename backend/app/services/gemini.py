"""Extraction through the Gemini API, as an alternative to a local model.

Two things differ from the LM Studio path and shape this client.

Gemini's `responseSchema` does not support `pattern`, which the local schema
leans on for dates, currency codes and the packed confidence string. So the
schema here states types and uses `enum` for confidence, one field per entity,
instead of a regex-constrained string. The validated result is identical: both
providers end at the same `validate_result`.

There is also no load or warm-up step. A hosted model is ready as soon as the
key is valid, which is why readiness for this provider means "the key works".
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction, PromptConfiguration
from app.services.field_validation import validate_result


BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_TIMEOUT_SECONDS = 300
CONFIDENCE_LEVELS = ["low", "medium", "high"]
THINKING_LEVELS = ("minimal", "low", "medium", "high")


from app.services.lm_studio import DOCUMENT_TEXT_HEADER


class GeminiError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeminiModel:
    id: str
    name: str
    supports_thinking: bool


# A curated list rather than everything the key can see: these are the two the
# app is set up for. `list_models` reports what the key actually exposes.
GEMINI_MODELS = (
    GeminiModel(id="gemini-3.7-flash", name="Gemini 3.7 Flash", supports_thinking=True),
    GeminiModel(id="gemini-3.5-flash-lite", name="Gemini 3.5 Flash Lite", supports_thinking=False),
)


def find_model(model_id: str) -> GeminiModel | None:
    return next((model for model in GEMINI_MODELS if model.id == model_id), None)


class GeminiClient:
    def __init__(self, api_key: str, thinking_level: str = "low") -> None:
        self.api_key = (api_key or "").strip()
        self.thinking_level = thinking_level if thinking_level in THINKING_LEVELS else "low"
        self.last_prediction_stats: dict[str, int | float] | None = None

    # -- schema ---------------------------------------------------------------

    @staticmethod
    def generation_schema(entities: list[EntityDefinition]) -> dict[str, Any]:
        """Build a proto `Schema`, which is not quite JSON Schema.

        Two differences bite. `type` is a scalar enum, so `["string", "null"]`
        is rejected with `Proto field is not repeating, cannot start list`;
        nullability is the separate `nullable` flag. And `pattern` does not
        exist here at all, so formats are stated in the description and enforced
        by the shared validation once the answer comes back.
        """
        types = {
            EntityFormat.decimal: "NUMBER",
            EntityFormat.integer: "INTEGER",
        }
        properties: dict[str, Any] = {}
        for entity in entities:
            description = entity.description
            if entity.format is EntityFormat.date:
                description = f"{description} Format the value as YYYY-MM-DD."
            elif entity.format is EntityFormat.currency:
                description = f"{description} Use the three-letter ISO 4217 code in upper case."
            properties[entity.name] = {
                "type": types.get(entity.format, "STRING"),
                "nullable": True,
                "description": description,
            }

        names = [entity.name for entity in entities]
        properties["confidence"] = {
            "type": "OBJECT",
            "description": "How sure you are of each value.",
            "properties": {
                name: {"type": "STRING", "enum": CONFIDENCE_LEVELS} for name in names
            },
            "required": names,
            "propertyOrdering": names,
        }
        return {
            "type": "OBJECT",
            "properties": properties,
            "required": [*names, "confidence"],
            # Key order affects output quality, and the values must be decided
            # before the model states how sure it is of them.
            "propertyOrdering": [*names, "confidence"],
        }

    # -- requests -------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise GeminiError("No Gemini API key is configured. Add one in Settings.")
        # Never the `?key=` query form: keys do not belong in URLs, which end up
        # in logs and in browser history.
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    async def list_models(self) -> list[str]:
        """Names the key can actually see. Used to check a key before relying on it."""
        headers = self._headers()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{BASE_URL}/models", headers=headers)
        except httpx.HTTPError as exc:
            raise GeminiError(f"Could not reach the Gemini API: {exc}") from exc
        self._raise_for_status(response)
        return [
            str(item.get("name", "")).removeprefix("models/")
            for item in response.json().get("models", [])
        ]

    async def extract_entities(
        self,
        model: str,
        images: list[str],
        prompts: PromptConfiguration,
        page_range: str,
        total_pages: int,
        processed_pages: int,
        document_text: str = "",
    ) -> dict[str, FieldExtraction]:
        headers = self._headers()
        page_note = (
            f"Only the first {processed_pages} of {total_pages} pages are supplied. "
            "Do not infer content from omitted pages. Return null for values that are not visible, "
            "and do not treat subtotals or carried-forward amounts as the final total."
            if processed_pages < total_pages
            else "All pages of the document are supplied."
        )
        user_text = f"{prompts.user_prompt.replace('{page_range}', page_range).strip()}\n\n{page_note}"
        if document_text.strip():
            user_text = f"{user_text}\n\n{DOCUMENT_TEXT_HEADER}\n\n{document_text.strip()}"
        parts: list[dict[str, Any]] = [{"text": user_text}]
        parts.extend(
            {"inlineData": {"mimeType": "image/png", "data": image}} for image in images
        )

        generation_config: dict[str, Any] = {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": self.generation_schema(prompts.entities),
        }
        selected = find_model(model)
        if selected is None or selected.supports_thinking:
            # Gemini 3 defaults to "high"; an extraction does not need to pay for
            # that, so the configured level is always stated.
            generation_config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}

        payload = {
            "systemInstruction": {"parts": [{"text": self._system_prompt(prompts)}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{BASE_URL}/models/{model}:generateContent",
                    json=payload,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise GeminiError(
                f"Gemini did not answer within {REQUEST_TIMEOUT_SECONDS} seconds."
            ) from exc
        except httpx.HTTPError as exc:
            raise GeminiError(f"Could not reach the Gemini API: {exc}") from exc

        self._raise_for_status(response)
        body = response.json()
        self.last_prediction_stats = self._prediction_stats(body)
        return self._parse(body, prompts.entities)

    # -- responses ------------------------------------------------------------

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        if response.status_code < 400:
            return
        detail = ""
        try:
            detail = str((response.json().get("error") or {}).get("message", ""))
        except Exception:  # noqa: BLE001 - the body may not be JSON at all
            detail = (response.text or "")[:300]

        if response.status_code in (401, 403):
            raise GeminiError(
                f"Gemini rejected the API key ({response.status_code}). "
                f"Check it in Settings. {detail}".strip()
            )
        if response.status_code == 429:
            raise GeminiError(f"Gemini rate limit or quota reached. {detail}".strip())
        if response.status_code == 404:
            raise GeminiError(
                f"Gemini does not know this model, or your key cannot use it. {detail}".strip()
            )
        raise GeminiError(f"Gemini returned {response.status_code}. {detail}".strip())

    @staticmethod
    def _parse(body: dict[str, Any], entities: list[EntityDefinition]) -> dict[str, FieldExtraction]:
        candidates = body.get("candidates") or []
        if not candidates:
            raise GeminiError("Gemini returned no answer for this document.")
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()

        if not text:
            raise GeminiError(
                f"Gemini returned an empty answer (finishReason={finish_reason or 'unknown'})."
            )
        if finish_reason == "MAX_TOKENS":
            raise GeminiError(
                "Gemini hit its output token limit before finishing the JSON object. "
                "Reduce the number of configured entities and try again."
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiError(f"Gemini did not return valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise GeminiError("Gemini did not return a JSON object.")

        confidence = payload.get("confidence")
        confidence = confidence if isinstance(confidence, dict) else {}
        expanded = {
            entity.name: {
                "value": payload.get(entity.name),
                "confidence": confidence.get(entity.name, "low")
                if confidence.get(entity.name) in CONFIDENCE_LEVELS
                else "low",
            }
            for entity in entities
        }
        return validate_result(expanded, entities)

    @staticmethod
    def _prediction_stats(body: dict[str, Any]) -> dict[str, int | float] | None:
        usage = body.get("usageMetadata") or {}
        prompt_tokens = usage.get("promptTokenCount")
        answer_tokens = usage.get("candidatesTokenCount") or 0
        # Thinking tokens are billed at the output rate, so they are counted there.
        thinking_tokens = usage.get("thoughtsTokenCount") or 0
        if prompt_tokens is None and not answer_tokens:
            return None
        stats: dict[str, int | float] = {
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(answer_tokens) + int(thinking_tokens),
        }
        if thinking_tokens:
            stats["thinking_tokens"] = int(thinking_tokens)
        return stats

    @staticmethod
    def _system_prompt(prompts: PromptConfiguration) -> str:
        entity_lines = "\n".join(
            f"- {entity.name} [{entity.format.value}]: {entity.description}"
            for entity in prompts.entities
        )
        return f"""{prompts.system_prompt.strip()}

Entities to extract:
{entity_lines}

{prompts.confidence_prompt.strip()}
Return one property per entity, named exactly as above, and a `confidence`
object holding one level per entity. Use null when a value is unavailable.
"""
