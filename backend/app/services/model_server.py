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

    async def list_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        if not self.base_url:
            return []
        try:
            async with httpx.AsyncClient(timeout=LIST_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{self.base_url}/v1/models", headers=await self._headers())
        except httpx.HTTPError as exc:
            raise LMStudioError(f"The model server at {self.base_url} is not reachable: {exc}") from exc
        if response.status_code != 200:
            raise LMStudioError(f"The model server answered {response.status_code} when asked for its models: {response.text[:200]}")
        excluded = set(excluded_model_ids or [])
        return [
            ModelInfo(
                id=str(item["id"]),
                name=str(item["id"]),
                provider="model_server",
                loaded=True,
                ready=True,
                runtime_state="ready",
                # The OpenAI listing reports ids only. Vision is not assumed
                # absent: the server says nothing either way.
                capabilities_known=False,
            )
            for item in response.json().get("data", [])
            if str(item.get("id")) not in excluded
        ]

    async def list_vision_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        return await self.list_models(excluded_model_ids)
