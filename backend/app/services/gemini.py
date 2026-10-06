"""Extraction through the Gemini API, as an alternative to a local model.

Two things differ from the LM Studio path and shape this client.

Gemini's `responseSchema` does not support `pattern`, which the local schema
leans on for dates, currency codes and the packed confidence string. So the
schema here states types and uses `enum` for confidence, one field per entity,
instead of a regex-constrained string. The validated result is identical: both
providers end at the same `validate_result`.

There is also no load or warm-up step. A hosted model is ready as soon as the
key is valid, which is why readiness for this provider means "the key works".

Two ways in. The Gemini API takes an API key. Vertex AI, when a deployment
configures it (DOCUFLOW_GEMINI_VERTEX_*), takes the identity the platform gives
the container instead: no key to hold, the project's own billing, and a
location that decides where documents are processed. The request and the
answer are the same.
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app import config
from app.domain.models import (
    EntityDefinition,
    EntityFormat,
    FieldExtraction,
    PromptConfiguration,
    model_entities,
)
from app.services.errors import ProviderError
from app.services.extraction_provider import ExtractionProvider
from app.services.field_validation import validate_result
from app.services.field_wording import described_for_reader


BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_TIMEOUT_SECONDS = 300
CONFIDENCE_LEVELS = ["low", "medium", "high"]
# The API also defines MINIMAL, but gemini-3.7-flash answers
# "Thinking level MINIMAL is not supported for this model", so offering it
# would only produce a 400 on every document. Measured on 2026-08-22: low
# spends about 60 thinking tokens on a small question, medium 190, high 230.
THINKING_LEVELS = ("low", "medium", "high")


class GeminiError(ProviderError):
    pass


@dataclass(frozen=True)
class GeminiModel:
    id: str
    name: str
    supports_thinking: bool


# A curated list rather than everything the key can see: these are the models the
# app is set up for. `list_models` reports what the key actually exposes.
GEMINI_MODELS = (
    GeminiModel(id="gemini-3.8-flash", name="Gemini 3.8 Flash", supports_thinking=True),
    GeminiModel(id="gemini-3.1-pro-preview", name="Gemini 3.1 Pro Preview", supports_thinking=True),
    GeminiModel(id="gemini-3.5-flash-lite", name="Gemini 3.5 Flash Lite", supports_thinking=False),
)


# Kept executable for saved experiments, but no longer offered for new runs.
LEGACY_GEMINI_MODELS = (GeminiModel(id="gemini-3.7-flash", name="Gemini 3.7 Flash", supports_thinking=True),)


def find_model(model_id: str) -> GeminiModel | None:
    return next((model for model in (*GEMINI_MODELS, *LEGACY_GEMINI_MODELS) if model.id == model_id), None)


def vertex_host(location: str) -> str:
    """Vertex AI's endpoint for a location: global, a multi-region such as eu, or a region."""
    if location == "global":
        return "https://aiplatform.googleapis.com"
    if location in ("eu", "us"):
        return f"https://aiplatform.{location}.rep.googleapis.com"
    return f"https://{location}-aiplatform.googleapis.com"


class GeminiClient(ExtractionProvider):
    def __init__(self, api_key: str, thinking_level: str = "low", location: str | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self.thinking_level = thinking_level if thinking_level in THINKING_LEVELS else "low"
        self.last_prediction_stats: dict[str, int | float] | None = None
        # A deployment that names Vertex AI uses it; the key is then not needed.
        # The location chosen in LLM replaces the deployment's, never silently.
        self.vertex = config.gemini_vertex()
        if self.vertex is not None and location:
            self.vertex = (self.vertex[0], location)

    @property
    def available(self) -> bool:
        return self.vertex is not None or bool(self.api_key)

    def _url(self, model: str) -> str:
        if self.vertex is not None:
            project, location = self.vertex
            return (
                f"{vertex_host(location)}/v1/projects/{project}/locations/{location}"
                f"/publishers/google/models/{model}:generateContent"
            )
        return f"{BASE_URL}/models/{model}:generateContent"

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
        entities = model_entities(entities)
        types = {
            EntityFormat.decimal: "NUMBER",
            EntityFormat.integer: "INTEGER",
        }
        properties: dict[str, Any] = {}
        for entity in entities:
            description = described_for_reader(entity)
            properties[entity.name] = {
                "type": types.get(entity.format, "STRING"),
                "nullable": True,
                "description": description,
            }
            if entity.format is EntityFormat.category and entity.categories:
                properties[entity.name].update(format="enum", enum=list(entity.categories))

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

    async def _headers(self) -> dict[str, str]:
        if self.vertex is not None:
            from app.services import gcp_runtime

            return {"Authorization": f"Bearer {await gcp_runtime.access_token()}", "Content-Type": "application/json"}
        if not self.api_key:
            raise GeminiError("No Gemini API key is configured. Add one in LLM.")
        # Never the `?key=` query form: keys do not belong in URLs, which end up
        # in logs and in browser history.
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    async def list_models(self) -> list[str]:
        """Names the key can actually see. Used to check a key before relying on it.

        Through Vertex AI there is no listing for a key: each model DocuFlow
        offers is asked for one token, and those that answer are reported.
        """
        if self.vertex is not None:
            return await self._vertex_models()
        headers = await self._headers()
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
        headers = await self._headers()
        user_text = self._user_text(
            prompts,
            page_range,
            total_pages=total_pages,
            processed_pages=processed_pages,
            document_text=document_text,
        )
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
        else:
            # The answer is all a model without thinking writes, so it gets
            # the same budget as a local one. Thinking tokens count against
            # the same limit, and nothing measured says how many a hard
            # invoice takes, so a thinking model is not capped here.
            generation_config["maxOutputTokens"] = self._output_token_budget(prompts.entities)

        payload = {
            "systemInstruction": {"parts": [{"text": self._system_prompt(prompts)}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(self._url(model), json=payload, headers=headers)
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

    async def _vertex_models(self) -> list[str]:
        return [check.model for check in await self.check_models() if check.status == "answering"]

    async def check_models(self) -> list[Any]:
        """One token from each model in this client's Vertex AI location."""
        from app.services import hosted_checks

        assert self.vertex is not None
        headers = await self._headers()
        probe = {
            "contents": [{"role": "user", "parts": [{"text": "Reply with OK"}]}],
            "generationConfig": {"maxOutputTokens": 1},
        }
        checks = []
        async with httpx.AsyncClient(timeout=60) as client:
            for model in GEMINI_MODELS:
                try:
                    response = await client.post(self._url(model.id), json=probe, headers=headers)
                except httpx.HTTPError as exc:
                    raise GeminiError(f"Could not reach Vertex AI: {exc}") from exc
                if response.status_code in (401, 403):
                    self._raise_for_status(response)
                detail = ""
                if response.status_code >= 400:
                    try:
                        detail = str((response.json().get("error") or {}).get("message", ""))
                    except Exception:  # noqa: BLE001 - the body may not be JSON at all
                        detail = (response.text or "")[:300]
                checks.append(hosted_checks.record(model.id, "google", self.vertex[1], response.status_code, detail))
        return checks

    # -- responses ------------------------------------------------------------

    def _raise_for_status(self, response: Any) -> None:
        if response.status_code < 400:
            return
        detail = ""
        try:
            detail = str((response.json().get("error") or {}).get("message", ""))
        except Exception:  # noqa: BLE001 - the body may not be JSON at all
            detail = (response.text or "")[:300]

        if response.status_code in (401, 403) and self.vertex is not None:
            raise GeminiError(
                f"Vertex AI refused this deployment's identity ({response.status_code}). {detail}".strip()
            )
        if response.status_code == 404 and self.vertex is not None:
            raise GeminiError(
                f"Vertex AI does not offer this model in location {self.vertex[1]}. {detail}".strip()
            )
        if response.status_code in (401, 403):
            raise GeminiError(
                f"Gemini rejected the API key ({response.status_code}). "
                f"The key is under LLM. {detail}".strip()
            )
        if response.status_code == 429:
            from app.services.hosted_checks import refusal_fact

            raise GeminiError(f"Gemini: {refusal_fact(429, detail)}")
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
                "Gemini hit its output token limit before finishing the JSON object, so "
                "the answer was cut off mid-value."
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiError(f"Gemini did not return valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise GeminiError("Gemini did not return a JSON object.")

        # A derived field is filled by a later step, or marked unfilled by one.
        # Materialised here as "not returned", it would hide that later warning.
        entities = model_entities(entities)
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
        # The proto schema has no length bound, so the ceiling LM Studio's
        # grammar enforces is applied to the answer instead.
        return ExtractionProvider._within_ceiling(validate_result(expanded, entities), entities)

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
        return f"""{prompts.system_prompt.strip()}

Entities to extract:
{ExtractionProvider._entity_lines(prompts)}

{prompts.confidence_prompt.strip()}
Return one property per entity, named exactly as above, and a `confidence`
object holding one level per entity. Use null when a value is unavailable.
"""
