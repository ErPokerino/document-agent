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
from typing import Any, Callable, ClassVar

import httpx
from pydantic import ValidationError

from app.services.field_validation import parse_named_value, validate_result
from app.services.host import (
    HostCapabilities,
    estimated_working_set_bytes,
    parameter_billions,
    parse_survey,
)
from app.domain.models import (
    EntityDefinition,
    EntityFormat,
    FieldExtraction,
    ModelInfo,
    PromptConfiguration,
    default_entities,
    model_entities,
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
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
# Settings that affect the request shape and runtime are owned by DocuFlow, not
# inherited from whichever values happen to be selected in LM Studio on one
# workstation. The accelerator choice can still adapt to the host, but the
# same model always gets the same context, batching and concurrency envelope.
MODEL_PROFILE_PARALLEL = 1
MODEL_PROFILE_CONTEXT_LENGTH = 8192
MODEL_PROFILE_EVAL_BATCH_SIZE = 512
MODEL_PROFILE_FLASH_ATTENTION = True
MODEL_PROFILE_OFFLOAD_KV_CACHE = False
MODEL_PROFILE_SEED = 0
# The longest a single extracted value may be. A schema sent to LM Studio
# becomes a grammar, and a grammar permitting an unbounded string permits one
# forever: a model too small for the document cannot answer with invalid JSON,
# so it stays inside an open value and repeats until the token budget or the
# request timeout ends it — ten minutes a document, on this bench. Bounded, the
# same model fails one field instantly and the run carries on. Set well above
# any real invoice field, so it never truncates an answer that was going well.
VALUE_CHARACTER_CEILING = 200
# A large model on CPU often fails the first image and succeeds on the next:
# qwen3.6-35b-a3b takes 95 seconds over a blank warm-up page and needed two
# goes. Each attempt reloads the model, so they are not cheap — but reporting a
# usable model as broken costs more.
VISION_WARMUP_ATTEMPTS = 3
VISION_WARMUP_SETTLE_SECONDS = 5


def loaded_profile_matches(config: dict[str, Any], *, cpu_safe: bool) -> bool:
    """Whether a loaded instance has the profile DocuFlow can apply to it.

    The CLI used for CPU-safe placement exposes only context and parallelism.
    Standard REST loads expose the complete set and are checked completely, so
    a small model loaded from the LM Studio UI cannot be mistaken for ours.
    """
    common = (
        config.get("parallel") == MODEL_PROFILE_PARALLEL
        and config.get("context_length") == MODEL_PROFILE_CONTEXT_LENGTH
    )
    if not common or cpu_safe:
        return common
    return (
        config.get("eval_batch_size") == MODEL_PROFILE_EVAL_BATCH_SIZE
        and config.get("flash_attention") is MODEL_PROFILE_FLASH_ATTENTION
        and config.get("offload_kv_cache_to_gpu") is MODEL_PROFILE_OFFLOAD_KV_CACHE
    )


def page_note(*, total_pages: int, processed_pages: int) -> str:
    """Tell the model how much of the document it is looking at.

    Both numbers, always. A model handed page 1 of a 7-page invoice and told
    nothing reads the first subtotal as the total; told the document is longer
    than what it can see, it returns null instead of guessing.
    """
    document = f"This document has {total_pages} page" + ("" if total_pages == 1 else "s")
    if processed_pages >= total_pages:
        if total_pages == 1:
            return f"{document}, and it is supplied here."
        return f"{document}, and all {total_pages} of them are supplied here."

    missing = total_pages - processed_pages
    seen = (
        "the first page only is supplied here"
        if processed_pages == 1
        else f"only the first {processed_pages} are supplied here"
    )
    return (
        f"{document}, and {seen}: {missing} page" + ("" if missing == 1 else "s") + " "
        "you cannot see follow. Do not infer anything from them. Return null for a value that "
        "is not visible on the pages you were given, and never treat a subtotal or a "
        "carried-forward amount as the final total."
    )



# LM Studio's REST API answers `Failed to load LLM 'x': Error: Failed to load
# model.` whatever went wrong — an unsupported architecture, a corrupt file, a
# memory failure. The CLI prints the reason under a "CAUSE" heading, so a
# failed load asks it and passes the answer on.
_CLI_CAUSE = re.compile(r"CAUSE\s*\n+\s*(?P<cause>.+?)\s*$", re.IGNORECASE | re.DOTALL)


def explain_load_failure(detail: str, cli_output: str) -> str:
    """`detail` with the cause the CLI reported, when it reported one."""
    match = _CLI_CAUSE.search(cli_output or "")
    if match is None:
        return detail
    cause = " ".join(match.group("cause").split())
    if not cause:
        return detail

    if "unknown model architecture" in cause:
        architecture = cause.split("unknown model architecture:", 1)[-1].strip().strip("'\"")
        return (
            f"LM Studio's runtime does not know the {architecture} architecture, so it cannot "
            f"open this model at all. This is a property of the installed runtime, not of "
            f"anything DocuFlow sends it."
        )
    return f"{detail} LM Studio reported: {cause}"


# LM Studio compiles one llama.cpp build per accelerator and lets exactly one
# be selected at a time, for the whole application. The choice matters here
# because `--gpu off` only holds the *model's* layers on the processor: the
# vision projector follows the engine. Load a large model with `--gpu off` on
# a Vulkan build and the page image is still encoded on the GPU, which is how
# an integrated adapter ends up losing its device mid-run.
_ACCELERATED_RUNTIMES = ("vulkan", "cuda", "rocm", "metal", "sycl")


def runtime_uses_gpu(alias: str | None) -> bool:
    """Whether this engine build talks to an accelerator.

    Unknown reads as no: an engine nobody recognises is more likely a plain
    build than a reason to warn someone who has nothing to act on.
    """
    lowered = (alias or "").lower()
    return any(marker in lowered for marker in _ACCELERATED_RUNTIMES)


def parse_selected_runtime(cli_output: str) -> str | None:
    """The GGUF engine `lms runtime ls` marks as selected, if any.

    Other model formats carry their own selection in the same table — the ASR
    engine has one — and they say nothing about how an LLM will run.
    """
    for line in (cli_output or "").splitlines():
        if "✓" not in line or "GGUF" not in line:
            continue
        alias = line.split()[0]
        if alias and alias != "LLM":
            return alias
    return None


# A large model often fails its very first image and succeeds on the next, so
# that one failure is worth another go. The test that matches this against
# what the engine mapper actually produces is the point: this used to be a
# substring of a sentence, and rewriting the sentence silently disabled every
# retry.
_VISION_STARTUP_FAILURE = ("failed to encode the page image", "vision encoder")


def is_vision_startup_failure(message: str) -> bool:
    """Whether this failure is the vision path stumbling as it starts."""
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _VISION_STARTUP_FAILURE)


def requires_cpu_safe_profile(
    quantization: str | None,
    size_bytes: int | None,
    params_string: str | None = None,
    host: HostCapabilities | None = None,
    architecture: str | None = None,
) -> bool:
    """Whether this model must be kept off the accelerator on *this* machine.

    Asked of the host rather than of a constant. What the accelerator can be
    trusted with is derived in `host.py`; what the model asks for is derived
    from its file and its parameter count. When the second exceeds the first,
    offloading is what loses the device mid-run.

    An unreadable host answers yes: offloading blind is the failure that costs
    a run. A host that was read and has no accelerator answers no, because its
    standard REST load is already processor-only and, unlike the CLI path, can
    apply the complete reproducible profile.
    """
    if host is None:
        return True
    if not host.accelerators:
        return False
    budget = host.offload_budget_bytes
    if budget <= 0:
        return True
    # Qwen 3.5 currently produces repeated/corrupted tokens when its text
    # layers are offloaded through Vulkan on the Intel UHD adapter measured by
    # this project. The same Q8 GGUF answers correctly on CPU; disabling flash
    # attention and switching between the 2.28.2 and 2.29.1 runtimes did not
    # change the Vulkan failure. Keep the workaround scoped to integrated-only
    # hosts so a dedicated GPU can still run this architecture normally.
    if host.has_integrated_only and (architecture or "").lower().startswith("qwen35"):
        return True
    # IQ codebook lookups are what first raised vk::Queue::submit:
    # ErrorDeviceLost, on an integrated adapter. The observation belongs to
    # that class of hardware, so it is not charged to a dedicated card.
    if host.has_integrated_only and (quantization or "").upper().startswith("IQ"):
        return True
    return estimated_working_set_bytes(size_bytes, params_string) > budget


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
        """Every model this LM Studio has, however it is willing to say so.

        Two endpoints answer. `/api/v1/models` is LM Studio's own and carries
        the size, quantization and capabilities the load profile is decided
        from. `/v1/models` is the OpenAI-compatible one, present in every
        build, and reports ids alone. Older installs have only the second, and
        asking one endpoint meant a working machine full of models looked like
        an empty one.
        """
        native, native_error = await self._get_json("/api/v1/models")
        if native is not None:
            return list(native.get("models") or [])

        compatible, compatible_error = await self._get_json("/v1/models")
        if compatible is not None:
            return [
                {
                    "type": "llm",
                    "key": item.get("id"),
                    "display_name": item.get("id"),
                    # Not "no capabilities": no answer about them. What the
                    # caller must not do is turn that into a claim.
                    "capabilities_known": False,
                    "loaded_instances": [],
                }
                for item in (compatible.get("data") or [])
                if item.get("id")
            ]

        raise LMStudioError(native_error or compatible_error or "LM Studio did not answer")

    async def _get_json(self, path: str) -> tuple[dict[str, Any] | None, str | None]:
        """The JSON at `path`, or a description of why there is none.

        The description is the point. Every failure here used to read "LM
        Studio is not reachable", which sends someone to restart a server that
        is already running and answering.
        """
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url)
        except httpx.ConnectError:
            return None, (
                f"Nothing is listening at {self.base_url}. LM Studio's local server is "
                f"started from its Developer tab, or with `lms server start`."
            )
        except httpx.TimeoutException:
            return None, f"LM Studio did not answer {path} within 10 seconds."
        except httpx.HTTPError as exc:
            return None, f"The request to {url} failed: {exc}"

        if response.status_code >= 400:
            return None, f"LM Studio answered {response.status_code} at {path}."
        try:
            payload = response.json()
        except ValueError:
            return None, f"LM Studio answered {path} with something that is not JSON."
        return (payload if isinstance(payload, dict) else {}), None

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
        host = await self.host_capabilities()
        models: list[ModelInfo] = []
        for item in await self._fetch_model_items():
            capabilities = item.get("capabilities") or {}
            capabilities_known = item.get("capabilities_known", True)
            if item.get("type") != "llm" or item.get("key") in excluded:
                continue
            loaded_instances = item.get("loaded_instances") or []
            loaded_config = (loaded_instances[0].get("config") or {}) if loaded_instances else {}
            quantization = (item.get("quantization") or {}).get("name")
            needs_safe = requires_cpu_safe_profile(
                quantization,
                item.get("size_bytes"),
                item.get("params_string"),
                host,
                item.get("architecture"),
            )
            parallel = loaded_config.get("parallel")
            profile_matches = not loaded_instances or loaded_profile_matches(
                loaded_config, cpu_safe=needs_safe
            )
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
                    profile_matches=profile_matches,
                    loaded=bool(loaded_instances),
                    vision=bool(capabilities.get("vision", False)),
                    capabilities_known=bool(capabilities_known),
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
        # False when the pipeline in use reads text rather than page images.
        # Some models answer text and kill the runtime on any image, so warming
        # up for vision they will never be asked for makes them unloadable.
        warm_vision: bool = True,
    ) -> dict[str, int | str | bool]:
        items = await self._fetch_model_items()
        llm_items = [item for item in items if item.get("type") == "llm"]
        if model not in {item.get("key") for item in llm_items}:
            raise LMStudioError("Select a model installed in LM Studio")
        selected_item = next(item for item in llm_items if item.get("key") == model)
        has_vision = bool((selected_item.get("capabilities") or {}).get("vision", False))
        quantization = ((selected_item.get("quantization") or {}).get("name") or "").upper()
        size_bytes = int(selected_item.get("size_bytes") or 0)
        large_model = requires_cpu_safe_profile(
            quantization, size_bytes, selected_item.get("params_string"),
            await self.host_capabilities(),
            selected_item.get("architecture"),
        )
        profile = "compatibility" if large_model else "standard"
        # A model without vision has no projector to initialize, so the only
        # thing worth warming is the structured-output path.
        has_vision = has_vision and warm_vision
        if not has_vision:
            warmup_mode = "schema"
        elif large_model:
            # Warming the schema path as well doubles the wait on a model the
            # host cannot offload, for a second capability the run does not
            # exercise until after the first image has already proved it.
            warmup_mode = "vision"
        else:
            warmup_mode = "vision_and_schema"
        selected_instances = selected_item.get("loaded_instances") or []
        already_loaded = bool(selected_instances)
        loaded_config = (selected_instances[0].get("config") or {}) if selected_instances else {}
        selected_profile_matches = bool(
            selected_instances and loaded_profile_matches(loaded_config, cpu_safe=large_model)
        )

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
        # LM Studio's model API does not echo the GPU-layer placement selected
        # by `lms load --gpu off`. After a backend restart, matching context
        # and parallelism therefore cannot prove that an already-loaded safe
        # model is actually on CPU. Reload it explicitly unless this backend
        # has already marked the instance ready and asked us to skip warm-up.
        if already_loaded and not skip_warmup and (large_model or not selected_profile_matches):
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
            if large_model and shutil.which("lms") is not None:
                load_ms = await self._load_large_model_with_cli(model)
            else:
                if large_model:
                    # No CLI on this machine, and the profile is mostly a load
                    # configuration that REST accepts. Only `--gpu off` needs
                    # the CLI, so that part is dropped and the report says so.
                    # Refusing to load anything at all was the worse answer:
                    # without the CLI the host cannot be surveyed either, so
                    # every model took this path and none could be loaded.
                    profile = "compatibility_partial"
                # Do not delegate these values to LM Studio. Its UI defaults
                # are local preferences, so doing so made the same 0.8B GGUF
                # run with a different context and parallelism on another PC.
                load_payload: dict[str, Any] = {
                    "model": model,
                    "echo_load_config": True,
                    "context_length": MODEL_PROFILE_CONTEXT_LENGTH,
                    "eval_batch_size": MODEL_PROFILE_EVAL_BATCH_SIZE,
                    "flash_attention": MODEL_PROFILE_FLASH_ATTENTION,
                    "offload_kv_cache_to_gpu": MODEL_PROFILE_OFFLOAD_KV_CACHE,
                    "parallel": MODEL_PROFILE_PARALLEL,
                }
                try:
                    load_response = await self._post_json(
                        "/api/v1/models/load",
                        load_payload,
                        timeout=600,
                    )
                except LMStudioError as exc:
                    # The REST answer says a load failed but not why. Ask the
                    # CLI, which prints the reason, before giving up.
                    raise LMStudioError(
                        explain_load_failure(str(exc), await self._cli_load_failure_cause(model))
                    ) from exc
                load_ms = round(float(load_response.get("load_time_seconds", 0)) * 1000)

        warmup_ms = 0
        preparation_attempts = 0
        if not skip_warmup:
            if phase_callback:
                phase_callback("warming_up")
            for attempt in range(VISION_WARMUP_ATTEMPTS):
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
                        and attempt < VISION_WARMUP_ATTEMPTS - 1
                        and is_vision_startup_failure(str(exc))
                    )
                    if not recoverable_vision_startup:
                        raise
                    if phase_callback:
                        phase_callback("loading")
                    # The runtime has just failed on an image; give it a moment
                    # to release what it was holding before asking again.
                    await asyncio.sleep(VISION_WARMUP_SETTLE_SECONDS)
                    if shutil.which("lms") is not None:
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
        """Load a large local model without GPU-layer offload.

        Nothing here is model-specific on purpose. This used to also pass
        --speculative-draft-mtp, which a model without a bundled MTP head
        rejects outright, so the safe profile was unavailable to exactly the
        large models that need it most.
        """
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
            str(MODEL_PROFILE_CONTEXT_LENGTH),
            "--parallel",
            str(MODEL_PROFILE_PARALLEL),
            "--identifier",
            model,
            "-y",
        ]
        started = time.perf_counter()

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                # `lms` prints spinner and box-drawing characters. Without this
                # Python decodes them with the console codepage — cp1252 here —
                # and the reader thread dies on the first one.
                encoding="utf-8",
                errors="replace",
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

    # The survey costs a subprocess and the answer changes only when someone
    # swaps hardware or picks another runtime in LM Studio, so it is held for
    # a short while rather than run on every model refresh.
    _host_cache: ClassVar[tuple[float, HostCapabilities] | None] = None
    HOST_CACHE_SECONDS: ClassVar[int] = 60

    async def host_capabilities(self) -> HostCapabilities | None:
        """What this machine can lend a model, or None if it cannot be read.

        None is not "no accelerator": it means the question went unanswered,
        and callers treat that as the careful case rather than assuming a card
        is there.
        """
        cached = LMStudioClient._host_cache
        if cached is not None and time.monotonic() - cached[0] < self.HOST_CACHE_SECONDS:
            return cached[1]

        from urllib.parse import urlparse

        if urlparse(self.base_url).hostname not in LOCAL_HOSTS:
            return None
        executable = shutil.which("lms")
        if executable is None:
            return None

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [executable, "runtime", "survey"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )

        try:
            completed = await asyncio.to_thread(run)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        host = parse_survey(completed.stdout or "")
        LMStudioClient._host_cache = (time.monotonic(), host)
        return host

    async def selected_runtime(self) -> str | None:
        """The engine LM Studio will use for GGUF models, if it can be read.

        Only the CLI exposes this — it is an application preference, not part
        of the server API — so a remote endpoint or a machine without `lms`
        yields None, and callers say nothing rather than guess.
        """
        from urllib.parse import urlparse

        if urlparse(self.base_url).hostname not in LOCAL_HOSTS:
            return None
        executable = shutil.which("lms")
        if executable is None:
            return None

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [executable, "runtime", "ls"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )

        try:
            completed = await asyncio.to_thread(run)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        return parse_selected_runtime(completed.stdout or "")

    async def _cli_load_failure_cause(self, model: str) -> str:
        """Run the CLI load so its error message can be read. Loads nothing.

        The load has already failed through REST, so this fails too — the point
        is the reason it prints, which the REST answer does not carry.
        """
        from urllib.parse import urlparse

        if urlparse(self.base_url).hostname not in LOCAL_HOSTS:
            return ""
        executable = shutil.which("lms")
        if executable is None:
            return ""

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [executable, "load", model, "--identifier", model, "-y"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )

        try:
            completed = await asyncio.to_thread(run)
        except (subprocess.TimeoutExpired, OSError):
            return ""
        return f"{completed.stdout or ''}\n{completed.stderr or ''}"

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
        # Qwen 3.5 on the measured Intel Vulkan runtime can satisfy a JSON
        # grammar while filling it with repeated multilingual garbage. A text
        # pipeline would therefore look warmed up and fail every document. A
        # tiny unconstrained answer catches that corruption; keep it off the
        # vision path, whose image request is already its runtime probe.
        if not include_image:
            await self._run_text_sanity_warmup(model)

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
            # Temperature zero removes sampling in normal cases; a fixed seed
            # also makes tie-breaking explicit instead of inheriting a runtime
            # or machine-specific default.
            "seed": MODEL_PROFILE_SEED,
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
            "seed": MODEL_PROFILE_SEED,
            "max_tokens": self._output_token_budget(entities),
            "stream": False,
        }
        await self._run_warmup_payload(
            schema_payload,
            lambda parsed: self._named_response_shape_is_valid(parsed, entities),
            "Entity schema",
        )

    async def _run_text_sanity_warmup(self, model: str) -> None:
        payload = {
            "model": model,
            "reasoning_effort": "none",
            "messages": [{"role": "user", "content": "Reply with exactly OK"}],
            "temperature": 0,
            "seed": MODEL_PROFILE_SEED,
            "max_tokens": 8,
            "stream": False,
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = await self._post_json(
                    "/v1/chat/completions",
                    payload,
                    timeout=600,
                )
                content = response["choices"][0]["message"]["content"]
                if isinstance(content, str) and content.strip().upper() == "OK":
                    return
                raise ValueError("response was not OK")
            except (KeyError, IndexError, ValueError) as exc:
                last_error = exc
        raise LMStudioError(f"Text generation warm-up failed: {last_error}")

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
        note = page_note(total_pages=total_pages, processed_pages=processed_pages)
        user_text = prompts.user_prompt.replace("{page_range}", page_range)
        user_text = f"{user_text.strip()}\n\n{note}"
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
            "seed": MODEL_PROFILE_SEED,
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
                        "object, so the answer was cut off mid-value. A model that cannot read "
                        "a field does not answer wrongly and stop: the schema's grammar forbids "
                        "invalid JSON, so it stays inside one value and keeps writing."
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
                "The Vulkan device was lost during inference: the GPU driver dropped the "
                "context the runtime was using, and LM Studio cannot continue with it."
            )
        if "failed to process image" in detail.lower():
            return (
                "LM Studio failed to encode the page image. Its log reports the Vulkan "
                "device being lost inside the vision encoder, which runs on the GPU even when "
                "the model's own layers are held on the processor."
            )
        if "exited before becoming healthy" in detail:
            return (
                "LM Studio's inference runtime crashed while loading this model, before it "
                "could serve anything. It reported no cause. Files that are not complete "
                "models — draft and MTP companions, interrupted downloads — fail at exactly "
                "this point."
            )
        if '"terminated"' in detail or "request terminated" in detail.lower():
            return (
                "LM Studio terminated the request because the model was unloaded, replaced, "
                "or stopped part way through inference."
            )
        return f"{prefix}: {detail}"

    @staticmethod
    def _system_prompt(prompts: PromptConfiguration) -> str:
        entity_lines = "\n".join(
            f"- {entity.name} [{entity.format.value}]: {entity.description}"
            for entity in model_entities(prompts.entities)
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
        entities = model_entities(entities)
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
                # Dates and currency codes are bounded by their own pattern
                # above; free text is the only value that could run on.
                value_schema = {"type": "string", "maxLength": VALUE_CHARACTER_CEILING}
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
        entities = model_entities(entities)
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
        entities = model_entities(entities)

        confidence_names = {"l": "low", "m": "medium", "h": "high"}
        expanded = {
            entity.name: {
                "value": parse_named_value(payload[entity.name], entity),
                "confidence": confidence_names[payload["c"][index]],
            }
            for index, entity in enumerate(entities)
        }
        return validate_result(expanded, entities)
