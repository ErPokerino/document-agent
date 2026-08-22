import base64
import asyncio
import binascii
import json
import re
import shutil
import struct
import subprocess
import time
import zlib
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Callable

import httpx
from pydantic import ValidationError

from app.services.field_validation import parse_named_value, validate_result
from app.domain.models import (
    EntityDefinition,
    EntityFormat,
    FieldExtraction,
    ModelInfo,
    PromptConfiguration,
    default_entities,
)


# Prefixed to the text an OCR or layout step produced, so the model knows
# where it came from and that it may trust it over its own reading.
DOCUMENT_TEXT_HEADER = (
    "A previous step read the document. Use this text as the source of truth for anything it contains:"
)


class LMStudioError(RuntimeError):
    pass


INFERENCE_TIMEOUT_SECONDS = 600
VISION_PREPARATION_TIMEOUT_SECONDS = 600
LARGE_MODEL_THRESHOLD_BYTES = 8 * 1024**3
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# What the CPU-safe profile looks like once applied. LM Studio's own default is
# four parallel slots, so `parallel` tells our instance apart from one it loaded
# on demand.
SAFE_PROFILE_PARALLEL = 1
SAFE_PROFILE_CONTEXT_LENGTH = 8192


def requires_cpu_safe_profile(quantization: str | None, size_bytes: int | None) -> bool:
    """Whether this model must be kept off the integrated GPU on this device.

    Both signals used to select a "compatibility" profile, but only the size one
    actually reached the CLI path that disables GPU offload; an IQ quant under
    the threshold was loaded through REST with the GPU still on, which is the
    configuration that raises vk::Queue::submit: ErrorDeviceLost.
    """
    return (quantization or "").upper().startswith("IQ") or int(size_bytes or 0) >= LARGE_MODEL_THRESHOLD_BYTES


@lru_cache(maxsize=1)
def _representative_warmup_image() -> str:
    width, height = 842, 1191
    row = b"\x00" + (b"\xff\xff\xff" * width)

    def png_chunk(kind: bytes, data: bytes) -> bytes:
        checksum = binascii.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    png = b"\x89PNG\r\n\x1a\n"
    png += png_chunk("IHDR".encode(), struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += png_chunk("IDAT".encode(), zlib.compress(row * height, level=9))
    png += png_chunk("IEND".encode(), b"")
    return base64.b64encode(png).decode("ascii")


class LMStudioClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.last_prediction_stats: dict[str, int | float] | None = None

    async def _fetch_model_items(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/v1/models")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LMStudioError("LM Studio is not reachable") from exc
        return response.json().get("models", [])

    async def list_vision_models(
        self,
        excluded_model_ids: list[str] | None = None,
    ) -> list[ModelInfo]:
        """Only the models that can read a page image."""
        return [model for model in await self.list_models(excluded_model_ids) if model.vision]

    async def list_models(
        self,
        excluded_model_ids: list[str] | None = None,
    ) -> list[ModelInfo]:
        """Every installed LLM, each saying whether it can see.

        Text-only models are listed because a pipeline that reads OCR text has
        no use for vision, and paying for it would be waste.
        """
        excluded = set(excluded_model_ids or [])
        models: list[ModelInfo] = []
        for item in await self._fetch_model_items():
            capabilities = item.get("capabilities") or {}
            if item.get("type") != "llm" or item.get("key") in excluded:
                continue
            loaded_instances = item.get("loaded_instances") or []
            loaded_config = (loaded_instances[0].get("config") or {}) if loaded_instances else {}
            quantization = (item.get("quantization") or {}).get("name")
            needs_safe = requires_cpu_safe_profile(quantization, item.get("size_bytes"))
            parallel = loaded_config.get("parallel")
            models.append(
                ModelInfo(
                    id=item["key"],
                    name=item.get("display_name") or item["key"],
                    parameters=item.get("params_string"),
                    quantization=quantization,
                    size_bytes=item.get("size_bytes"),
                    context_length=loaded_config.get("context_length"),
                    parallel=parallel,
                    requires_safe_profile=needs_safe,
                    profile_matches=(
                        not loaded_instances
                        or not needs_safe
                        or parallel == SAFE_PROFILE_PARALLEL
                    ),
                    loaded=bool(loaded_instances),
                    vision=bool(capabilities.get("vision", False)),
                )
            )
        models.sort(
            key=lambda model: (
                model.size_bytes is None,
                model.size_bytes or 0,
                model.name.lower(),
            )
        )
        return models

    async def load_and_warm_model(
        self,
        model: str,
        *,
        skip_warmup: bool = False,
        phase_callback: Callable[[str], None] | None = None,
        entities: list[EntityDefinition] | None = None,
    ) -> dict[str, int | str | bool]:
        items = await self._fetch_model_items()
        llm_items = [item for item in items if item.get("type") == "llm"]
        if model not in {item.get("key") for item in llm_items}:
            raise LMStudioError("Select a model installed in LM Studio")
        selected_item = next(item for item in llm_items if item.get("key") == model)
        has_vision = bool((selected_item.get("capabilities") or {}).get("vision", False))
        quantization = ((selected_item.get("quantization") or {}).get("name") or "").upper()
        size_bytes = int(selected_item.get("size_bytes") or 0)
        large_model = requires_cpu_safe_profile(quantization, size_bytes)
        profile = "compatibility" if large_model else "default"
        # A model without vision has no projector to initialize, so the only
        # thing worth warming is the structured-output path.
        if not has_vision:
            warmup_mode = "schema"
        elif size_bytes >= LARGE_MODEL_THRESHOLD_BYTES:
            warmup_mode = "vision"
        else:
            warmup_mode = "vision_and_schema"
        selected_instances = selected_item.get("loaded_instances") or []
        already_loaded = bool(selected_instances)

        started = time.perf_counter()
        unloaded_models = 0
        for item in llm_items:
            if item.get("key") == model:
                continue
            for instance in item.get("loaded_instances") or []:
                await self._post_json(
                    "/api/v1/models/unload",
                    {"instance_id": instance["id"]},
                    timeout=120,
                )
                unloaded_models += 1

        # On this machine LM Studio's automatic GPU choice overcommits the
        # integrated GPU/shared RAM for 27B models. If the backend has not
        # already prepared the model, reload it with GPU layers disabled so
        # the Load action establishes a deterministic, safe runtime profile.
        if large_model and already_loaded and not skip_warmup:
            for instance in selected_instances:
                await self._post_json(
                    "/api/v1/models/unload",
                    {"instance_id": instance["id"]},
                    timeout=120,
                )
            already_loaded = False

        load_ms = 0
        if not already_loaded:
            if phase_callback:
                phase_callback("loading")
            if large_model:
                load_ms = await self._load_large_model_with_cli(model)
            else:
                load_payload: dict[str, Any] = {
                    "model": model,
                    "echo_load_config": True,
                }
                if profile == "compatibility":
                    load_payload.update(
                        {
                            "context_length": 8192,
                            "eval_batch_size": 512,
                            "flash_attention": True,
                            "offload_kv_cache_to_gpu": False,
                            "parallel": 1,
                        }
                    )
                load_response = await self._post_json(
                    "/api/v1/models/load",
                    load_payload,
                    timeout=600,
                )
                load_ms = round(float(load_response.get("load_time_seconds", 0)) * 1000)

        warmup_ms = 0
        preparation_attempts = 0
        if not skip_warmup:
            if phase_callback:
                phase_callback("warming_up")
            for attempt in range(2):
                preparation_attempts += 1
                warmup_started = time.perf_counter()
                try:
                    await self._warm_up_structured_output(
                        model,
                        entities or default_entities(),
                        include_schema=warmup_mode != "vision",
                        include_image=has_vision,
                    )
                    warmup_ms += round((time.perf_counter() - warmup_started) * 1000)
                    break
                except LMStudioError as exc:
                    warmup_ms += round((time.perf_counter() - warmup_started) * 1000)
                    recoverable_vision_startup = (
                        large_model
                        and attempt == 0
                        and "processing the document image" in str(exc)
                    )
                    if not recoverable_vision_startup:
                        raise
                    if phase_callback:
                        phase_callback("loading")
                    load_ms += await self._reload_large_model_with_cli(model)
                    if phase_callback:
                        phase_callback("warming_up")
        return {
            "model": model,
            "status": "ready",
            "load_ms": load_ms,
            "warmup_ms": warmup_ms,
            "total_ms": round((time.perf_counter() - started) * 1000),
            "unloaded_models": unloaded_models,
            "profile": profile,
            "already_loaded": already_loaded,
            "already_ready": already_loaded and skip_warmup,
            "warmup_mode": warmup_mode,
            "preparation_attempts": preparation_attempts,
        }

    async def _reload_large_model_with_cli(self, model: str) -> int:
        for item in await self._fetch_model_items():
            if item.get("key") != model:
                continue
            for instance in item.get("loaded_instances") or []:
                await self._post_json(
                    "/api/v1/models/unload",
                    {"instance_id": instance["id"]},
                    timeout=120,
                )
        return await self._load_large_model_with_cli(model)

    async def _load_large_model_with_cli(self, model: str) -> int:
        """Load a large local model without GPU-layer offload."""
        from urllib.parse import urlparse

        if urlparse(self.base_url).hostname not in LOCAL_HOSTS:
            raise LMStudioError(
                "The CPU-safe large-model profile is available only for a local LM Studio endpoint."
            )
        executable = shutil.which("lms")
        if executable is None:
            raise LMStudioError(
                "LM Studio CLI was not found. Install or enable `lms`, then retry Load."
            )

        command = [
            executable,
            "load",
            model,
            "--gpu",
            "off",
            "--context-length",
            str(SAFE_PROFILE_CONTEXT_LENGTH),
            "--parallel",
            str(SAFE_PROFILE_PARALLEL),
            "--identifier",
            model,
            "--speculative-draft-mtp",
            "-y",
        ]
        started = time.perf_counter()

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )

        try:
            completed = await asyncio.to_thread(run)
        except subprocess.TimeoutExpired as exc:
            raise LMStudioError("LM Studio did not load the large model within 600 seconds") from exc
        except OSError as exc:
            raise LMStudioError(f"LM Studio CLI could not be started: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown CLI error").strip()[:800]
            raise LMStudioError(f"LM Studio could not apply the CPU-safe model profile: {detail}")
        # The CLI can return before the vision projector accepts its first
        # image. A short settling window prevents an immediate false failure.
        await asyncio.sleep(10)
        return round((time.perf_counter() - started) * 1000)

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.base_url}{path}", json=payload)
                response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:800]
            raise LMStudioError(self._friendly_engine_error(detail, "Model loading failed")) from exc
        except httpx.HTTPError as exc:
            if path == "/v1/chat/completions":
                raise LMStudioError(
                    "LM Studio did not complete model preparation. The model is installed, "
                    "but it is not ready for document extraction on the current runtime."
                ) from exc
            raise LMStudioError("LM Studio stopped responding while loading the model") from exc

    async def _warm_up_structured_output(
        self,
        model: str,
        entities: list[EntityDefinition],
        *,
        include_schema: bool = True,
        include_image: bool = True,
    ) -> None:
        # A single generated token is enough to initialize the vision projector.
        # Running a full structured generation here can itself get stuck and is
        # not representative of document extraction performance.
        vision_payload = {
            "model": model,
            "reasoning_effort": "none",
            "messages": [
                {
                    "role": "system",
                    "content": "Return only JSON that matches the supplied schema.",
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Inspect this blank warm-up page and reply OK.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_representative_warmup_image()}"
                            },
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 1,
            "stream": False,
        }
        if include_image:
            await self._post_json(
                "/v1/chat/completions",
                vision_payload,
                timeout=VISION_PREPARATION_TIMEOUT_SECONDS,
            )

        if not include_schema:
            return

        schema_payload = {
            "model": model,
            "reasoning_effort": "none",
            "messages": [
                {
                    "role": "system",
                    "content": "Return only JSON that matches the supplied document extraction schema.",
                },
                {
                    "role": "user",
                    "content": (
                        "Warm up the configured extraction schema. Return null for every named "
                        "entity property and one l per entity in c."
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "document_extraction",
                    "strict": True,
                    "schema": self._generation_schema(entities),
                },
            },
            "temperature": 0,
            "max_tokens": self._output_token_budget(entities),
            "stream": False,
        }
        await self._run_warmup_payload(
            schema_payload,
            lambda parsed: self._named_response_shape_is_valid(parsed, entities),
            "Entity schema",
        )

    async def _run_warmup_payload(
        self,
        payload: dict[str, Any],
        is_valid: Callable[[Any], bool],
        label: str,
    ) -> None:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await self._post_json(
                    "/v1/chat/completions",
                    payload,
                    timeout=600,
                )
                raw_content = response["choices"][0]["message"]["content"]
                parsed = json.loads(raw_content)
                if is_valid(parsed):
                    return
                raise ValueError("response did not match the warm-up schema")
            except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
        raise LMStudioError(f"{label} warm-up failed: {last_error}")

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
        page_note = (
            f"Only the first {processed_pages} of {total_pages} pages are supplied. "
            "Do not infer content from omitted pages. Return null for values that are not visible, "
            "and do not treat subtotals or carried-forward amounts as the final total."
            if processed_pages < total_pages
            else "All pages of the document are supplied."
        )
        user_text = prompts.user_prompt.replace("{page_range}", page_range)
        user_text = f"{user_text.strip()}\n\n{page_note}"
        if document_text.strip():
            user_text = f"{user_text}\n\n{DOCUMENT_TEXT_HEADER}\n\n{document_text.strip()}"
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        content.extend(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}}
            for image in images
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(prompts)},
            {"role": "user", "content": content},
        ]
        return await self._request_entities(model, messages, prompts.entities)

    async def _request_entities(
        self,
        model: str,
        messages: list[dict[str, Any]],
        entities: list[EntityDefinition],
    ) -> dict[str, FieldExtraction]:
        payload = {
            "model": model,
            "reasoning_effort": "none",
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "document_extraction",
                    "strict": True,
                    "schema": self._generation_schema(entities),
                },
            },
            "temperature": 0,
            # Keep a hard ceiling: grammar-constrained models can otherwise
            # remain inside an unfinished JSON structure for many minutes.
            "max_tokens": self._output_token_budget(entities),
            "stream": False,
        }

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=INFERENCE_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self.base_url}/api/v0/chat/completions",
                        json=payload,
                    )
                    response.raise_for_status()
                response_data = response.json()
                self.last_prediction_stats = self._prediction_stats(response_data)
                choice = response_data["choices"][0]
                if choice.get("finish_reason") == "length":
                    # Retrying only adds prompt tokens, so it can never recover
                    # from an exhausted output budget. Fail with the real cause.
                    raise LMStudioError(
                        "The model reached its output token limit before finishing the JSON "
                        "object. Reduce the number of configured entities, or shorten their "
                        "names, and run the extraction again."
                    )
                raw_content = choice["message"]["content"]
                if not isinstance(raw_content, str) or not raw_content.strip():
                    raise ValueError(
                        f"empty response (finish_reason={choice.get('finish_reason', 'unknown')})"
                    )
                parsed = json.loads(raw_content)
                return self._validate_named_result(parsed, entities)
            except httpx.HTTPStatusError as exc:
                detail = exc.response.text[:600]
                raise LMStudioError(
                    self._friendly_engine_error(detail, "LM Studio rejected the request")
                ) from exc
            except httpx.TimeoutException as exc:
                raise LMStudioError(
                    f"The model did not finish within {INFERENCE_TIMEOUT_SECONDS} seconds. "
                    "The request was not repeated, "
                    "so the reported processing time does not include hidden retries."
                ) from exc
            except httpx.HTTPError as exc:
                raise LMStudioError("LM Studio stopped responding during inference") from exc
            except (KeyError, IndexError, json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    payload["messages"] = [
                        *messages,
                        {
                            "role": "user",
                            "content": "The previous response did not match the required format or values. "
                            "Try again. Return only the exact named entity properties and the compact c string.",
                        },
                    ]

        raise LMStudioError(f"The model did not produce valid JSON: {last_error}")

    @staticmethod
    def _prediction_stats(response_data: dict[str, Any]) -> dict[str, int | float] | None:
        stats = response_data.get("stats") or {}
        usage = response_data.get("usage") or {}
        if not stats:
            return None
        result: dict[str, int | float] = {}
        mappings = {
            "time_to_first_token_seconds": stats.get("time_to_first_token"),
            "prediction_time_seconds": stats.get("generation_time"),
            "tokens_per_second": stats.get("tokens_per_second"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }
        for key, value in mappings.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = value
        return result or None

    @staticmethod
    def _friendly_engine_error(detail: str, prefix: str) -> str:
        if "ErrorDeviceLost" in detail or "DeviceLost" in detail:
            return (
                "The GPU/Vulkan device was lost during inference. Reload the model from "
                "Settings; DocuFlow will use a conservative single-model profile."
            )
        if "failed to process image" in detail.lower():
            return (
                "LM Studio stopped while processing the document image. Reload the model from "
                "Settings; large models will use the low-memory single-request profile."
            )
        if "exited before becoming healthy" in detail:
            return (
                "LM Studio's inference runtime crashed while loading this model, before it "
                "could serve anything. The model file is the usual cause: draft and MTP "
                "companion files are not complete models and always fail this way, and so do "
                "interrupted downloads. Verify the model in LM Studio, or select another one."
            )
        if '"terminated"' in detail or "request terminated" in detail.lower():
            return (
                "LM Studio terminated the request because the model was unloaded, replaced, "
                "or stopped during inference. Wait until the model is ready, then retry."
            )
        return f"{prefix}: {detail}"

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
Return each value in the JSON property with its exact entity name.
Return decimal and integer entities as JSON numbers without symbols or thousands separators.
Return other entities as JSON strings. Use null when a value is unavailable.
c is one confidence-code string in the same order, with l=low, m=medium, h=high.
Return only JSON that conforms to the supplied schema.
"""

    @staticmethod
    def _generation_schema(entities: list[EntityDefinition]) -> dict[str, Any]:
        item_count = len(entities)
        value_keys = [entity.name for entity in entities]
        properties: dict[str, Any] = {}
        for entity in entities:
            if entity.format is EntityFormat.decimal:
                value_schema: dict[str, Any] = {"type": "number"}
            elif entity.format is EntityFormat.integer:
                value_schema = {"type": "integer"}
            elif entity.format is EntityFormat.date:
                value_schema = {
                    "type": "string",
                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                }
            elif entity.format is EntityFormat.currency:
                value_schema = {"type": "string", "pattern": "^[A-Z]{3}$"}
            else:
                value_schema = {"type": "string"}
            properties[entity.name] = {
                "description": entity.description,
                "anyOf": [value_schema, {"type": "null"}],
            }
        properties["c"] = {
            "type": "string",
            "pattern": f"^[lmh]{{{item_count}}}$",
            "minLength": item_count,
            "maxLength": item_count,
        }
        return {
            "type": "object",
            "properties": properties,
            "required": [*value_keys, "c"],
            "additionalProperties": False,
        }

    @staticmethod
    def _output_token_budget(entities: list[EntityDefinition]) -> int:
        # The property names are part of the generated output, so a schema with
        # long names needs a larger budget than one with short names. Roughly
        # one token per three characters of key, plus room for the value and the
        # JSON punctuation around each property.
        key_tokens = sum(max(1, len(entity.name) // 3) for entity in entities)
        return 128 + key_tokens + len(entities) * 32

    @staticmethod
    def _named_response_shape_is_valid(
        payload: Any,
        entities: list[EntityDefinition],
    ) -> bool:
        item_count = len(entities)
        expected_keys = {entity.name for entity in entities} | {"c"}
        return (
            isinstance(payload, dict)
            and set(payload) == expected_keys
            and isinstance(payload.get("c"), str)
            and len(payload["c"]) == item_count
            and all(code in "lmh" for code in payload["c"])
        )

    @staticmethod
    def _validate_named_result(
        payload: Any,
        entities: list[EntityDefinition],
    ) -> dict[str, FieldExtraction]:
        if not LMStudioClient._named_response_shape_is_valid(payload, entities):
            raise ValueError("The response does not contain one named value and confidence per entity")

        confidence_names = {"l": "low", "m": "medium", "h": "high"}
        expanded = {
            entity.name: {
                "value": parse_named_value(payload[entity.name], entity),
                "confidence": confidence_names[payload["c"][index]],
            }
            for index, entity in enumerate(entities)
        }
        return validate_result(expanded, entities)
