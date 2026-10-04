"""Open models served behind an OpenAI-compatible API: llama.cpp, vLLM, Ollama, TGI.

What runs a local model on a server rather than on this machine. The request
is the one LM Studio is sent — the same prompt, schema-constrained output,
temperature and seed — at the standard `/v1/chat/completions` path; only the
transport differs. Nothing is loaded or warmed from here: the server holds the
model it was started with, so a model it lists is a model it can answer with.

Where the server is, and how to prove who is calling, is deployment
configuration (DOCUFLOW_MODEL_SERVER_*), not a setting a user edits: a server
behind Google sign-in on Cloud Run takes an identity token, one behind a
gateway a bearer token, one on a private network nothing.
"""

import re
from typing import Any

import httpx

from app import config
from app.domain.models import ModelInfo
from app.services.lm_studio import INFERENCE_TIMEOUT_SECONDS, LMStudioClient, LMStudioError

# Listing models is quick unless the server is starting; a scaled-to-zero
# service needs its model loaded before it answers anything at all.
LIST_TIMEOUT_SECONDS = 120


class ModelServerClient(LMStudioClient):
    server_name = "The model server"

    def __init__(self, base_url: str | None = None) -> None:
        super().__init__(base_url if base_url is not None else config.model_server_url())

    async def _headers(self) -> dict[str, str]:
        mode = config.model_server_auth()
        if mode == "none":
            return {}
        if mode == "bearer":
            return {"Authorization": f"Bearer {config.model_server_token()}"}
        if mode == "google_id_token":
            from app.services import gcp_runtime

            return {"Authorization": f"Bearer {await gcp_runtime.identity_token(self.base_url)}"}
        raise LMStudioError(f"DOCUFLOW_MODEL_SERVER_AUTH={mode!r} is not one of: none, bearer, google_id_token")

    async def _post_chat(self, payload: dict[str, Any]) -> httpx.Response:
        async with httpx.AsyncClient(timeout=INFERENCE_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload, headers=await self._headers())
            response.raise_for_status()
        return response

    @staticmethod
    def _prediction_stats(response_data: dict[str, Any]) -> dict[str, int | float] | None:
        """Token counts from the standard `usage`, and speed from llama.cpp's `timings`.

        LM Studio puts its figures under `stats`; a server that has neither
        reports nothing rather than zeros.
        """
        usage = response_data.get("usage") or {}
        timings = response_data.get("timings") or {}
        figures = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "prediction_time_seconds": timings["predicted_ms"] / 1000 if isinstance(timings.get("predicted_ms"), (int, float)) else None,
            "tokens_per_second": timings.get("predicted_per_second"),
        }
        result = {key: value for key, value in figures.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
        return result or None

    async def _get(self, client: httpx.AsyncClient, path: str) -> httpx.Response:
        try:
            return await client.get(f"{self.base_url}{path}", headers=await self._headers())
        except httpx.HTTPError as exc:
            raise LMStudioError(f"The model server at {self.base_url} is not reachable: {exc}") from exc

    async def list_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        """What the server serves, with what it says about each model.

        The OpenAI listing gives ids only. llama.cpp adds what LM Studio
        reports for a local model — parameters, quantization, size, context —
        and, in `/props`, whether the model reads images. A server that says
        nothing more is listed with its ids and capabilities marked unknown,
        never guessed.
        """
        if not self.base_url:
            return []
        async with httpx.AsyncClient(timeout=LIST_TIMEOUT_SECONDS) as client:
            response = await self._get(client, "/v1/models")
            if response.status_code != 200:
                raise LMStudioError(f"The model server answered {response.status_code} when asked for its models: {response.text[:200]}")
            listing = response.json()
            props: dict[str, Any] = {}
            try:
                answer = await self._get(client, "/props")
                if answer.status_code == 200:
                    props = answer.json()
            except LMStudioError:
                props = {}
        capabilities = {
            str(entry.get("model") or entry.get("name")): entry.get("capabilities") or []
            for entry in listing.get("models", [])
            if isinstance(entry, dict)
        }
        modalities = props.get("modalities") if isinstance(props.get("modalities"), dict) else None
        slots = props.get("total_slots")
        excluded = set(excluded_model_ids or [])
        models = []
        for item in listing.get("data", []):
            model_id = str(item.get("id"))
            if model_id in excluded:
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            if model_id in capabilities and capabilities[model_id]:
                vision: bool | None = "multimodal" in capabilities[model_id] or "vision" in capabilities[model_id]
            elif modalities is not None:
                vision = bool(modalities.get("vision"))
            else:
                vision = None
            models.append(
                ModelInfo(
                    id=model_id,
                    name=model_id,
                    provider="model_server",
                    parameters=parameter_count(meta.get("n_params")),
                    quantization=quantization(meta.get("ftype"), props.get("model_path")),
                    size_bytes=int(meta["size"]) if isinstance(meta.get("size"), (int, float)) else None,
                    context_length=int(meta["n_ctx"]) if isinstance(meta.get("n_ctx"), (int, float)) else None,
                    parallel=int(slots) if isinstance(slots, int) else None,
                    loaded=True,
                    ready=True,
                    runtime_state="ready",
                    capabilities_known=vision is not None,
                    vision=True if vision is None else vision,
                )
            )
        return models

    async def list_vision_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        return await self.list_models(excluded_model_ids)


def parameter_count(value: Any) -> str | None:
    """7518069290 → "7.5B", the way LM Studio writes it."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    billions = f"{value / 1e9:.1f}".rstrip("0").rstrip(".")
    return f"{billions}B"


def quantization(ftype: Any, model_path: Any = None) -> str | None:
    """llama.cpp's "Q4_K - Medium" as the file name writes it, "Q4_K_M"."""
    if isinstance(ftype, str) and ftype.strip():
        name = ftype.strip()
        for words, suffix in ((" - Medium", "_M"), (" - Small", "_S"), (" - Large", "_L")):
            if name.endswith(words):
                return name[: -len(words)] + suffix
        return name.replace(" ", "")
    if isinstance(model_path, str):
        found = re.search(r"[-_.]((?:I?Q\d\w*?)|BF16|F16|F32)\.gguf$", model_path, re.IGNORECASE)
        if found:
            return found.group(1).upper()
    return None
