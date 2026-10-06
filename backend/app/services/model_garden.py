"""Google Model Garden partner transports. No partner API keys are used."""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app import config
from app.domain.models import FieldExtraction, PromptConfiguration
from app.services.errors import ProviderError
from app.services.extraction_provider import ExtractionProvider
from app.services.gemini import GeminiClient, vertex_host
from app.services import gcp_runtime, hosted_checks


@dataclass(frozen=True)
class PartnerModel:
    id: str
    name: str
    publisher: str
    preview: bool = False
    supports_thinking: bool = True


PARTNER_MODELS = (
    PartnerModel("claude-sonnet-5-5", "Claude Sonnet 5.5", "anthropic"),
    PartnerModel("claude-opus-5-5", "Claude Opus 5.5", "anthropic"),
    PartnerModel("grok-4.7", "Grok 4.7", "xai", True),
)


# Where each publisher's models can be asked. Grok has no EU endpoint.
LOCATIONS = {"anthropic": ("eu", "us", "global"), "xai": ("us", "global")}


def find_partner(model: str) -> PartnerModel | None:
    return next((item for item in PARTNER_MODELS if item.id == model), None)


def endpoint(selected: PartnerModel, project: str, location: str) -> str:
    base = f"{vertex_host(location)}/v1/projects/{project}/locations/{location}"
    if selected.publisher == "anthropic":
        return f"{base}/publishers/anthropic/models/{selected.id}:rawPredict"
    return f"{base}/endpoints/openapi/chat/completions"


def refusal_detail(body: object) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message", ""))
    return str(error or "")


def connection(model: str, settings: Any) -> tuple[str, str]:
    selected = find_partner(model)
    if selected is None:
        raise ProviderError(f"Model Garden has no configured model named {model}.")
    project = config.model_garden_project()
    if not project:
        raise ProviderError("No Model Garden project is configured for this deployment.")
    location = settings.claude_location if selected.publisher == "anthropic" else settings.grok_location
    return project, location


def generation_schema(entities: list) -> dict[str, Any]:
    """JSON Schema, rather than Gemini's proto dialect."""
    def convert(value: dict) -> dict:
        out = {key: item for key, item in value.items() if key not in ("nullable", "propertyOrdering", "format")}
        kind = str(out.get("type", "")).lower()
        out["type"] = [kind, "null"] if value.get("nullable") else kind
        if "properties" in out:
            out["properties"] = {key: convert(item) for key, item in out["properties"].items()}
            out["additionalProperties"] = False
        return out
    return convert(GeminiClient.generation_schema(entities))


def grok_output_tokens(usage: dict[str, Any]) -> int | None:
    """Google reports reasoning separately; total_tokens avoids double counting.

    The live Model Garden response has completion=24, reasoning=72, input=588,
    total=684. OpenAI's convention that completion includes reasoning does not
    apply to that response. Retain compatibility if a response does include it.
    """
    completion = usage.get("completion_tokens")
    if completion is None:
        return None
    total, prompt = usage.get("total_tokens"), usage.get("prompt_tokens")
    if total is not None and prompt is not None:
        return total - prompt if total >= prompt + completion else None
    return completion + (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)


class ModelGardenClient(ExtractionProvider):
    def __init__(self, settings: Any, project: str | None = None, location: str | None = None) -> None:
        self.settings = settings
        self.project_override = project
        self.location_override = location
        self.last_prediction_stats = None
        self.last_usage: dict[str, Any] | None = None
        self.http_status: int | None = None
        self.request_id: str | None = None
        self.retry_after: float = 1

    async def extract_entities(
        self, model: str, images: list[str], prompts: PromptConfiguration,
        page_range: str, total_pages: int, processed_pages: int, document_text: str = "",
    ) -> dict[str, FieldExtraction]:
        self.last_prediction_stats = self.last_usage = None
        self.http_status = None
        self.request_id = None
        project, location = connection(model, self.settings)
        project = self.project_override or project
        location = self.location_override or location
        selected = find_partner(model)
        assert selected is not None
        if location not in LOCATIONS[selected.publisher]:
            raise ProviderError(f"{selected.name} is not offered in location {location}.")
        text = self._user_text(prompts, page_range, total_pages=total_pages,
                               processed_pages=processed_pages, document_text=document_text)
        schema = generation_schema(prompts.entities)
        if selected.publisher == "anthropic":
            url = endpoint(selected, project, location)
            content = [{"type": "text", "text": text}, *[
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": value}}
                for value in images
            ]]
            payload = {
                "anthropic_version": "vertex-2023-10-16", "max_tokens": self.settings.output_limit(selected.publisher),
                "system": GeminiClient._system_prompt(prompts),
                "messages": [{"role": "user", "content": content}],
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": self.settings.effort("anthropic"),
                                  "format": {"type": "json_schema", "schema": schema}},
            }
        else:
            url = endpoint(selected, project, location)
            content = [{"type": "text", "text": text}, *[
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{value}"}}
                for value in images
            ]]
            payload = {
                "model": f"xai/{model}", "max_completion_tokens": self.settings.output_limit(selected.publisher),
                # Accepted by Grok 4.7 on Vertex AI (checked 2026-10-06); it reasons either way.
                "reasoning_effort": self.settings.effort("xai"),
                "messages": [{"role": "system", "content": GeminiClient._system_prompt(prompts)},
                             {"role": "user", "content": content}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "extraction", "strict": True, "schema": schema}},
            }
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(url, json=payload, headers={
                    "Authorization": f"Bearer {await gcp_runtime.access_token()}", "Content-Type": "application/json",
                })
        except httpx.HTTPError as exc:
            raise ProviderError(f"Model Garden request failed: {exc}") from exc
        self.http_status = response.status_code
        self.request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        try:
            self.retry_after = min(60, max(1, float(response.headers.get("retry-after", "1"))))
        except ValueError:
            self.retry_after = 1
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(f"Model Garden returned {response.status_code} without a JSON response.") from exc
        if not isinstance(body, dict):
            raise ProviderError(f"Model Garden returned {response.status_code} without a JSON object.")
        if response.status_code != 200:
            fact = hosted_checks.refusal_fact(response.status_code, refusal_detail(body))
            raise ProviderError(f"{selected.name} in {location}, project {project}: {fact}")
        self.last_usage = body.get("usage") or {}
        usage = self.last_usage
        if selected.publisher == "anthropic":
            input_count = usage.get("input_tokens")
            output_count = usage.get("output_tokens")
            cache = usage.get("cache_read_input_tokens", 0)
            writes = usage.get("cache_creation_input_tokens", 0)
            answer = "".join(part.get("text", "") for part in body.get("content", []) if part.get("type") == "text")
            stop = body.get("stop_reason")
        else:
            input_count = usage.get("prompt_tokens")
            output_count = grok_output_tokens(usage)
            cache = writes = 0
            choices = body.get("choices") or [{}]
            answer = (choices[0].get("message") or {}).get("content") or ""
            stop = choices[0].get("finish_reason")
        self.last_prediction_stats = {}
        if input_count is not None:
            self.last_prediction_stats["prompt_tokens"] = int(input_count) + int(cache) + int(writes)
        if output_count is not None:
            self.last_prediction_stats["completion_tokens"] = int(output_count)
        if stop in ("max_tokens", "length", "refusal", "content_filter"):
            raise ProviderError(f"{model} ended the answer with {stop}.")
        try:
            parsed = json.loads(answer)
        except (ValueError, TypeError) as exc:
            raise ProviderError(f"{model} returned no valid JSON object.") from exc
        if not isinstance(parsed, dict):
            raise ProviderError(f"{model} returned no JSON object.")
        # Share validation and value bounds with the existing hosted extractor.
        return GeminiClient._parse({"candidates": [{"content": {"parts": [{"text": json.dumps(parsed)}]}}]}, prompts.entities)

    async def check(self, model: str, location: str) -> "hosted_checks.HostedModelCheck":
        """Ask for one token, so a refusal shows up before a run and not inside it.

        Google checks quota before it reads the request, so a model with no
        quota is refused here exactly as it would be by an extraction.
        """
        selected = find_partner(model)
        if selected is None:
            raise ProviderError(f"Model Garden has no configured model named {model}.")
        project = self.project_override or config.model_garden_project()
        if not project:
            raise ProviderError("No Model Garden project is configured for this deployment.")
        if location not in LOCATIONS[selected.publisher]:
            return hosted_checks.record(model, selected.publisher, location, 404)
        prompt = [{"role": "user", "content": "Reply with OK"}]
        payload: dict[str, Any] = (
            {"anthropic_version": "vertex-2023-10-16", "max_tokens": 1, "messages": prompt}
            if selected.publisher == "anthropic"
            else {"model": f"xai/{model}", "max_completion_tokens": 1, "messages": prompt}
        )
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(endpoint(selected, project, location), json=payload, headers={
                    "Authorization": f"Bearer {await gcp_runtime.access_token()}", "Content-Type": "application/json",
                })
        except httpx.HTTPError as exc:
            return hosted_checks.record_unreachable(model, selected.publisher, location, f"Model Garden was not reachable: {exc}")
        try:
            body = response.json()
        except ValueError:
            body = {}
        return hosted_checks.record(model, selected.publisher, location, response.status_code, refusal_detail(body))
