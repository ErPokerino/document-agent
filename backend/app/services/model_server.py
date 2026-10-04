"""Open models served behind an OpenAI-compatible API: llama.cpp, vLLM, Ollama, TGI.

What runs a local model on a server rather than on this machine. The request
is the one LM Studio is sent — the same prompt, schema-constrained output,
temperature and seed — at the standard `/v1/chat/completions` path; only the
transport differs.

Two kinds of server are understood:

- **One model, fixed when the server started.** Whatever `/v1/models` lists is
  ready; there is nothing to load.
- **A llama.cpp router** (`llama-server --models-preset …`), which knows many
  models and holds those it was asked to load. `GET /models` says which are
  loaded; DocuFlow loads one explicitly and warms it up, exactly as it does
  with LM Studio, so loading never lands inside a document's timer. With
  `--models-max 1` loading one unloads the previous.

What the deployment says about each model — parameters, quantization, size,
vision — can come from a catalog file beside the models
(DOCUFLOW_MODEL_SERVER_CATALOG); a server reports little about a model it has
not loaded.

Where the server is, and how to prove who is calling, is deployment
configuration (DOCUFLOW_MODEL_SERVER_*), not a setting a user edits: a server
behind Google sign-in on Cloud Run takes an identity token, one behind a
gateway a bearer token, one on a private network nothing.
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from app import config
from app.domain.models import EntityDefinition, ModelInfo
from app.services.lm_studio import INFERENCE_TIMEOUT_SECONDS, LMStudioClient, LMStudioError

# Listing models is quick unless the server is starting from zero.
LIST_TIMEOUT_SECONDS = 120
# The largest model read from object storage takes minutes to load.
LOAD_TIMEOUT_SECONDS = 20 * 60
LOAD_POLL_SECONDS = 2.0

_ROUTER_STATES = {
    "loaded": "ready",
    "sleeping": "ready",
    "loading": "loading",
    "downloading": "loading",
    "unloaded": "not_loaded",
}


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

    async def _post_json(self, path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        """The warm-up requests LM Studio's client sends, with this server's credentials."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.base_url}{path}", json=payload, headers=await self._headers())
                response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise LMStudioError(f"The model server refused the warm-up ({exc.response.status_code}): {exc.response.text[:400]}") from exc
        except httpx.HTTPError as exc:
            raise LMStudioError(f"The model server stopped responding during the warm-up: {exc}") from exc

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

    async def _router_entries(self, client: httpx.AsyncClient) -> list[dict[str, Any]] | None:
        """The router's models with their status, or None when the server is not a router."""
        response = await self._get(client, "/models")
        if response.status_code != 200:
            return None
        try:
            entries = response.json().get("data")
        except ValueError:
            return None
        if not isinstance(entries, list) or not entries or not all(isinstance(entry, dict) and "status" in entry for entry in entries):
            return None
        return entries

    async def list_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        """What the server serves, with what is known about each model.

        Nothing is guessed: a figure neither the server nor the catalog gives
        stays blank, and a capability nobody reports is marked unknown.
        """
        if not self.base_url:
            return []
        excluded = set(excluded_model_ids or [])
        async with httpx.AsyncClient(timeout=LIST_TIMEOUT_SECONDS) as client:
            entries = await self._router_entries(client)
            response = await self._get(client, "/v1/models")
            if response.status_code != 200:
                raise LMStudioError(f"The model server answered {response.status_code} when asked for its models: {response.text[:200]}")
            listing = response.json()
            props: dict[str, Any] = {}
            if entries is None:
                answer = await self._get(client, "/props")
                if answer.status_code == 200:
                    props = answer.json()
        # What a loaded model reports about itself, by id.
        meta = {
            str(item.get("id")): item.get("meta") if isinstance(item.get("meta"), dict) else {}
            for item in listing.get("data", [])
            if isinstance(item, dict)
        }
        catalog = _catalog()
        if entries is not None:
            return [
                self._router_model(entry, meta.get(str(entry.get("id")), {}), catalog.get(str(entry.get("id")), {}))
                for entry in entries
                if str(entry.get("id")) not in excluded
            ]
        return [
            self._single_model(model_id, meta[model_id], listing, props, catalog.get(model_id, {}))
            for model_id in meta
            if model_id not in excluded
        ]

    @staticmethod
    def _router_model(entry: dict[str, Any], meta: dict[str, Any], described: dict[str, Any]) -> ModelInfo:
        status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
        value = str(status.get("value") or "unloaded")
        runtime_state = "error" if status.get("failed") else _ROUTER_STATES.get(value, "not_loaded")
        arguments = [str(argument) for argument in status.get("args") or []]
        modalities = (entry.get("architecture") or {}).get("input_modalities") if isinstance(entry.get("architecture"), dict) else None
        if isinstance(described.get("vision"), bool):
            vision: bool | None = described["vision"]
        elif isinstance(modalities, list):
            vision = "image" in modalities
        else:
            vision = None
        context = _argument(arguments, "-c", "--ctx-size")
        return ModelInfo(
            id=str(entry.get("id")),
            name=str(entry.get("id")),
            provider="model_server",
            parameters=described.get("parameters") or parameter_count(meta.get("n_params")),
            quantization=described.get("quantization") or quantization(meta.get("ftype"), entry.get("path")),
            size_bytes=described.get("size_bytes") if isinstance(described.get("size_bytes"), int) else (int(meta["size"]) if isinstance(meta.get("size"), (int, float)) else None),
            context_length=int(meta["n_ctx"]) if isinstance(meta.get("n_ctx"), (int, float)) else context,
            parallel=_argument(arguments, "-np", "--parallel"),
            loaded=runtime_state == "ready",
            ready=runtime_state == "ready",
            runtime_state=runtime_state,  # type: ignore[arg-type]
            capabilities_known=vision is not None,
            vision=True if vision is None else vision,
        )

    @staticmethod
    def _single_model(model_id: str, meta: dict[str, Any], listing: dict[str, Any], props: dict[str, Any], described: dict[str, Any]) -> ModelInfo:
        capabilities = {
            str(entry.get("model") or entry.get("name")): entry.get("capabilities") or []
            for entry in listing.get("models", [])
            if isinstance(entry, dict)
        }
        modalities = props.get("modalities") if isinstance(props.get("modalities"), dict) else None
        if isinstance(described.get("vision"), bool):
            vision: bool | None = described["vision"]
        elif capabilities.get(model_id):
            vision = "multimodal" in capabilities[model_id] or "vision" in capabilities[model_id]
        elif modalities is not None:
            vision = bool(modalities.get("vision"))
        else:
            vision = None
        slots = props.get("total_slots")
        return ModelInfo(
            id=model_id,
            name=model_id,
            provider="model_server",
            parameters=described.get("parameters") or parameter_count(meta.get("n_params")),
            quantization=described.get("quantization") or quantization(meta.get("ftype"), props.get("model_path")),
            size_bytes=int(meta["size"]) if isinstance(meta.get("size"), (int, float)) else described.get("size_bytes"),
            context_length=int(meta["n_ctx"]) if isinstance(meta.get("n_ctx"), (int, float)) else None,
            parallel=int(slots) if isinstance(slots, int) else None,
            # A server started with one model has nothing else to load.
            loaded=True,
            ready=True,
            runtime_state="ready",
            capabilities_known=vision is not None,
            vision=True if vision is None else vision,
        )

    async def load_and_warm_model(
        self,
        model: str,
        *,
        entities: list[EntityDefinition],
        warm_vision: bool = True,
        phase_callback: Callable[[str], None] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Have the server load `model`, then warm it the way LM Studio's models are warmed.

        Load and warm-up are timed apart from any document, as locally. A model
        the server already holds is not loaded or warmed again.
        """
        started = time.perf_counter()
        before = {model_info.id: model_info for model_info in await self.list_models()}
        selected = before.get(model)
        if selected is None:
            raise LMStudioError(f"The model server does not serve {model}.")
        if selected.ready:
            return _load_report(model, already=True, load_ms=0, warmup_ms=0, started=started, unloaded=0, mode="schema")
        others_loaded = sum(1 for model_id, info in before.items() if model_id != model and info.loaded)
        if phase_callback:
            phase_callback("loading")
        async with httpx.AsyncClient(timeout=LIST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(f"{self.base_url}/models/load", json={"model": model}, headers=await self._headers())
            except httpx.HTTPError as exc:
                raise LMStudioError(f"The model server at {self.base_url} is not reachable: {exc}") from exc
            if response.status_code >= 300:
                raise LMStudioError(f"The model server refused to load {model} ({response.status_code}): {response.text[:300]}")
        deadline = time.monotonic() + LOAD_TIMEOUT_SECONDS
        while True:
            current = next((info for info in await self.list_models() if info.id == model), None)
            if current is not None and current.ready:
                break
            if current is not None and current.runtime_state == "error":
                raise LMStudioError(f"The model server could not load {model}. Its log says why.")
            if time.monotonic() > deadline:
                raise LMStudioError(f"{model} was not loaded within {LOAD_TIMEOUT_SECONDS // 60} minutes.")
            await asyncio.sleep(LOAD_POLL_SECONDS)
        load_ms = round((time.perf_counter() - started) * 1000)
        has_vision = warm_vision and current.vision and current.capabilities_known
        mode = "vision_and_schema" if has_vision else "schema"
        if phase_callback:
            phase_callback("warming_up")
        warmup_started = time.perf_counter()
        try:
            await self._warm_up_structured_output(model, entities, include_schema=True, include_image=has_vision)
        except LMStudioError:
            # Loaded but not answering properly: let it go, so it is not
            # listed as ready and no run starts on it.
            await self._unload(model)
            raise
        warmup_ms = round((time.perf_counter() - warmup_started) * 1000)
        return _load_report(model, already=False, load_ms=load_ms, warmup_ms=warmup_ms, started=started, unloaded=others_loaded, mode=mode)

    async def _unload(self, model: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=LIST_TIMEOUT_SECONDS) as client:
                await client.post(f"{self.base_url}/models/unload", json={"model": model}, headers=await self._headers())
        except httpx.HTTPError:
            # The failure being reported matters more than this one.
            pass

    async def list_vision_models(self, excluded_model_ids: list[str] | None = None) -> list[ModelInfo]:
        return await self.list_models(excluded_model_ids)


def _load_report(model: str, *, already: bool, load_ms: int, warmup_ms: int, started: float, unloaded: int, mode: str) -> dict[str, Any]:
    return {
        "model": model,
        "status": "ready",
        "load_ms": load_ms,
        "warmup_ms": warmup_ms,
        "total_ms": round((time.perf_counter() - started) * 1000),
        "unloaded_models": unloaded,
        "profile": "server",
        "already_loaded": already,
        "already_ready": already,
        "warmup_mode": mode,
        "preparation_attempts": 0 if already else 1,
    }


def _catalog() -> dict[str, dict[str, Any]]:
    """What the deployment wrote about its models (deploy/gcp/upload-models.sh), if anything."""
    path = config.model_server_catalog()
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)} if isinstance(data, dict) else {}


def _argument(arguments: list[str], *names: str) -> int | None:
    for index, argument in enumerate(arguments[:-1]):
        if argument in names and arguments[index + 1].isdigit():
            return int(arguments[index + 1])
    return None


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
