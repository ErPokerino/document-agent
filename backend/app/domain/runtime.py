"""The models a machine can run, how they are loaded, and the profile a run records."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


# What a run records as its model when its pipeline cannot call one, rather
# than whichever model happens to be selected.
MODEL_NOT_USED = "Not used"


class RuntimeEngineInfo(BaseModel):
    """Which llama.cpp build LM Studio will run a local model on, and on what.

    `--gpu off` holds a model's own layers on the processor but leaves the
    vision projector on whatever this engine targets, so a GPU build and a
    CPU-safe load are not the same thing.

    The accelerator and the budget are reported because they decide how every
    model here is loaded. On a machine DocuFlow has never seen, that decision
    is the thing worth being able to check.
    """

    engine: str | None = None
    uses_gpu: bool = False
    accelerator: str | None = None
    accelerator_bytes: int | None = None
    accelerator_integrated: bool = False
    # How much model this host will be trusted to hold. Zero means every model
    # is loaded on the processor; null means the machine could not be read.
    offload_budget_bytes: int | None = None


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: Literal["lm_studio", "gemini", "model_server"] = "lm_studio"
    parameters: str | None = None
    quantization: str | None = None
    size_bytes: int | None = None
    context_length: int | None = None
    parallel: int | None = None
    # A large or IQ-quantized model offloaded to this machine's integrated GPU
    # loses the Vulkan device, so those are loaded with `--gpu off`. That covers
    # the model's layers only; see RuntimeEngineInfo for what it does not.
    requires_safe_profile: bool = False
    # False when the loaded instance was not the one we prepared: LM Studio
    # loads on demand with its own defaults, and that instance crashes here.
    profile_matches: bool = True
    loaded: bool = False
    ready: bool = False
    # False when the model was found through the OpenAI-compatible endpoint,
    # which reports ids and nothing else. `vision` is then not a claim that
    # the model cannot see, only that nothing here knows whether it can.
    capabilities_known: bool = True
    runtime_state: Literal[
        "not_loaded", "loaded", "loading", "warming_up", "ready", "error", "profile_mismatch"
    ] = "not_loaded"
    vision: bool = True


class ModelLoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: Annotated[str, Field(min_length=1, max_length=500)]


class ModelLoadResponse(BaseModel):
    model: str
    status: Literal["ready"] = "ready"
    load_ms: int
    warmup_ms: int
    total_ms: int
    unloaded_models: int
    # "compatibility_partial" is the CPU-safe profile minus the one part
    # only the LM Studio CLI can set: holding the layers off the GPU.
    # "server": loaded by a model server, which holds its own load settings.
    profile: Literal["standard", "compatibility", "compatibility_partial", "server"]
    already_loaded: bool = False
    already_ready: bool = False
    warmup_mode: Literal["vision", "schema", "vision_and_schema"]
    preparation_attempts: int = 0


class ModelExecutionProfile(BaseModel):
    """The provider settings that can change an otherwise identical run."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["lm_studio", "gemini", "model_server"]
    profile: Literal["standard", "compatibility", "compatibility_partial", "hosted", "server"]
    parameters: str | None = None
    quantization: str | None = None
    model_size_bytes: int | None = None
    temperature: float = 0
    seed: int | None = None
    reasoning_effort: str | None = None
    thinking_level: str | None = None
    context_length: int | None = None
    parallel: int | None = None
    eval_batch_size: int | None = None
    flash_attention: bool | None = None
    offload_kv_cache_to_gpu: bool | None = None


class HealthStatus(BaseModel):
    status: str
    lm_studio: bool
    # False where this deployment runs no LM Studio (DOCUFLOW_LM_STUDIO=off):
    # not a fault to report, and nothing to connect to.
    lm_studio_enabled: bool = True
    # Whether a model server is configured for this deployment.
    model_server: bool = False
    active_model: str
    # Why the local models are missing, when they are. /api/models answers with
    # the hosted ones alone rather than failing outright, which is right — and
    # left nobody with a reason for the empty half of the list.
    lm_studio_error: str | None = None
