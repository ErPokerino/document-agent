"""This machine, and the models on it."""

from fastapi import HTTPException, APIRouter

from app.api import deps
from app.domain.models import (
    HealthStatus,
    ModelInfo,
    RuntimeEngineInfo,
    ModelLoadRequest,
    ModelLoadResponse,
)
from app.pipeline.definition import requires_vision
from app.services.gemini import find_model
from app.services.lm_studio import LMStudioError, runtime_uses_gpu

router = APIRouter()


@router.get("/api/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    settings = deps.settings_store.read()
    reason: str | None = None
    try:
        await deps.LMStudioClient(settings.lm_studio_url).list_models()
        connected = True
    except LMStudioError as exc:
        connected = False
        reason = str(exc)
    return HealthStatus(
        status="ok" if connected else "degraded",
        lm_studio=connected,
        active_model=settings.model,
        lm_studio_error=reason,
    )


@router.get("/api/models", response_model=list[ModelInfo])
async def models() -> list[ModelInfo]:
    settings = deps.settings_store.read()
    hosted = deps.hosted_models(settings)
    try:
        discovered = await deps.LMStudioClient(settings.lm_studio_url).list_models(
            settings.excluded_model_ids
        )
    except LMStudioError as exc:
        # One provider being unreachable must not hide the other. Only report a
        # failure when there is nothing at all to choose from.
        if not hosted:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return hosted
    resolved = deps.unique_model_alias(settings.model, discovered)
    if settings.provider == "lm_studio" and resolved is not None and resolved.id != settings.model:
        # Discovery awaited the network. Re-read before writing so a prompt or
        # pipeline saved in the meantime is never replaced by this migration's
        # stale snapshot.
        deps.settings_store.update(
            lambda latest: latest.model_copy(update={"model": resolved.id})
            if latest.provider == "lm_studio" and latest.model == settings.model
            else latest
        )
    return [*deps.models_with_runtime_state(discovered), *hosted]


@router.get("/api/runtime-engine", response_model=RuntimeEngineInfo)
async def runtime_engine() -> RuntimeEngineInfo:
    settings = deps.settings_store.read()
    client = deps.LMStudioClient(settings.lm_studio_url)
    engine = await client.selected_runtime()
    host = await client.host_capabilities()
    best = (
        max(host.accelerators, key=lambda adapter: adapter.memory_bytes)
        if host and host.accelerators
        else None
    )
    return RuntimeEngineInfo(
        engine=engine,
        uses_gpu=runtime_uses_gpu(engine),
        accelerator=best.name if best else None,
        accelerator_bytes=best.memory_bytes if best else None,
        accelerator_integrated=bool(best and best.integrated),
        offload_budget_bytes=host.offload_budget_bytes if host else None,
    )


@router.post("/api/models/load", response_model=ModelLoadResponse)
async def load_model(request: ModelLoadRequest) -> ModelLoadResponse:
    settings = deps.settings_store.read()
    if find_model(request.model) is not None:
        raise HTTPException(
            status_code=400,
            detail="This model runs on Google's servers and does not need loading. "
            "Add an API key in LLM and it is ready.",
        )
    if request.model in settings.excluded_model_ids:
        raise HTTPException(
            status_code=400,
            detail="This model is excluded on this device because it did not pass local compatibility testing.",
        )
    client = deps.LMStudioClient(settings.lm_studio_url)
    async with deps.exclusive_model_operation("loading"):
        previous_runtime_state = deps.model_runtime_states.get(request.model)
        deps.model_runtime_states[request.model] = "loading"

        def update_phase(phase: str) -> None:
            deps.active_model_operation = phase
            deps.model_runtime_states[request.model] = phase

        try:
            discovered = await client.list_models()
            selected = next((model for model in discovered if model.id == request.model), None)
            already_ready = bool(
                selected
                and selected.loaded
                and previous_runtime_state == "ready"
            )
            result = await client.load_and_warm_model(
                request.model,
                skip_warmup=already_ready,
                phase_callback=update_phase,
                entities=settings.prompts.entities,
                warm_vision=requires_vision(deps.selected_pipeline(settings)),
            )
            for model_id in list(deps.model_runtime_states):
                if model_id != request.model:
                    deps.model_runtime_states[model_id] = "not_loaded"
                    deps.model_runtime_profiles.pop(model_id, None)
            deps.model_runtime_states[request.model] = "ready"
            deps.model_warmup_modes[request.model] = str(result["warmup_mode"])
            deps.model_runtime_profiles[request.model] = str(result["profile"])
            # Re-read rather than write back the snapshot this request
            # started with: a load takes minutes, and anything chosen in the
            # meantime — a pipeline, above all — would be reverted by it.
            deps.settings_store.update(
                lambda latest: latest.model_copy(update={"model": request.model})
            )
            return ModelLoadResponse.model_validate(result)
        except LMStudioError as exc:
            deps.model_runtime_states[request.model] = "error"
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except BaseException:
            # Includes CancelledError, raised whenever the browser tab is closed
            # during a multi-minute load. Without this the model would stay
            # "loading" forever and both Load and Extract would refuse to run.
            deps.model_runtime_states[request.model] = "error"
            raise
