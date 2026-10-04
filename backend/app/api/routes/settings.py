"""Configuration: entities, prompts, the chosen model and pipeline, and credentials."""

from fastapi import HTTPException, Response, APIRouter

from app import config
from app.api import deps
from app.domain.models import (
    AppSettings,
    GcpKeyStatus,
    GeminiKeyStatus,
    PromptPreview,
    PromptPreviewRequest,
)
from app.pipeline.definition import requires_vision
from app.pipeline.store import InvalidPipelineName, UnknownPipeline
from app.services.document_ai import DocumentAiClient, DocumentAiError
from app.services.gemini import GEMINI_MODELS, GeminiError, find_model
from app.services.lm_studio import LMStudioError

router = APIRouter()


@router.get("/api/settings", response_model=AppSettings)
async def get_settings() -> AppSettings:
    return deps.masked(deps.settings_store.read())


@router.post("/api/prompts/preview", response_model=PromptPreview)
async def preview_prompt(request: PromptPreviewRequest) -> PromptPreview:
    """Show exactly what the model will be sent.

    The prompt a user writes is only the opening: the app appends the entity
    list, the confidence rubric and the format rules, and builds a schema from
    the entities. Assembling it here rather than in the browser means the
    preview cannot drift away from what actually goes out.
    """
    import json as _json

    # Imported here, not through the module-level names: this is pure prompt
    # assembly with no network in it, and it must show the real formatting even
    # when the network clients are substituted.
    from app.services.gemini import GeminiClient as Gemini
    from app.services.lm_studio import LMStudioClient as LMStudio

    if request.provider == "gemini":
        return PromptPreview(
            provider="gemini",
            system_prompt=Gemini._system_prompt(request.prompts),
            generation_schema=_json.dumps(
                Gemini.generation_schema(request.prompts.entities), indent=2
            ),
        )
    return PromptPreview(
        provider="lm_studio",
        system_prompt=LMStudio._system_prompt(request.prompts),
        generation_schema=_json.dumps(
            LMStudio._generation_schema(request.prompts.entities), indent=2
        ),
        output_token_budget=LMStudio._output_token_budget(request.prompts.entities),
    )


@router.get("/api/settings/gemini", response_model=GeminiKeyStatus)
async def gemini_key_status() -> GeminiKeyStatus:
    return deps.key_status(deps.settings_store.read())


@router.post("/api/settings/gemini/verify", response_model=GeminiKeyStatus)
async def verify_gemini_key() -> GeminiKeyStatus:
    """Ask Google what this key can see, so a bad key fails here and not mid-run."""
    settings = deps.settings_store.read()
    if not settings.gemini.api_key.strip():
        raise HTTPException(status_code=400, detail="Add a Gemini API key first.")
    try:
        available = await deps.GeminiClient(settings.gemini.api_key).list_models()
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    supported = {model.id for model in GEMINI_MODELS}
    return deps.key_status(settings, verified=[name for name in available if name in supported])


@router.delete("/api/settings/gemini", status_code=204, response_class=Response)
async def clear_gemini_key() -> Response:
    deps.settings_store.update(
        lambda latest: latest.model_copy(
            update={"gemini": latest.gemini.model_copy(update={"api_key": ""})}
        )
    )
    return Response(status_code=204)


@router.put("/api/settings", response_model=AppSettings)
async def update_settings(settings: AppSettings) -> AppSettings:
    previous_settings = deps.settings_store.read()
    # Catalog mutations have their own validation and must survive stale settings forms.
    settings.gcp.processors = previous_settings.gcp.processors
    try:
        chosen_pipeline = deps.pipeline_store.read(settings.pipeline)
    except (UnknownPipeline, InvalidPipelineName) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if settings.model in settings.excluded_model_ids:
        raise HTTPException(
            status_code=400,
            detail="The active model cannot also be excluded on this device",
        )

    # The key is write-only: an empty field means "leave the stored one alone",
    # which is what the masked value the UI holds always sends back.
    if not settings.gemini.api_key.strip():
        settings = settings.model_copy(
            update={
                "gemini": settings.gemini.model_copy(
                    update={"api_key": previous_settings.gemini.api_key}
                )
            }
        )

    # A rate is for a hosted model DocuFlow knows: one that can be chosen, or
    # a retired one whose old runs still need costing.
    unknown_rates = sorted(model for model in settings.gemini.pricing if find_model(model) is None)
    if unknown_rates:
        raise HTTPException(
            status_code=400,
            detail=f"No hosted model is named {', '.join(unknown_rates)}, so it has no price to set.",
        )

    if settings.provider == "gemini":
        if find_model(settings.model) is None:
            raise HTTPException(
                status_code=400,
                detail=f"{settings.model} is not one of the supported hosted models.",
            )
    else:
        # Prompts and entities must stay editable while LM Studio is down; only a
        # change of target model or endpoint needs the live model list.
        endpoint_changed = settings.lm_studio_url != previous_settings.lm_studio_url
        provider_changed = settings.provider != previous_settings.provider
        if settings.model != previous_settings.model or endpoint_changed or provider_changed:
            # A model server holds its models; LM Studio is asked only about its own.
            served = settings.provider == "model_server"
            if not served and not config.lm_studio_enabled():
                raise HTTPException(status_code=400, detail="LM Studio is not part of this deployment. Choose another model.")
            try:
                available = await (
                    deps.ModelServerClient().list_models()
                    if served
                    else deps.LMStudioClient(settings.lm_studio_url).list_models()
                )
            except LMStudioError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            chosen = next(
                (model for model in available if model.id == settings.model), None
            )
            if chosen is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"The model server does not serve {settings.model}."
                        if served
                        else "Select a model installed in LM Studio"
                    ),
                )
            # Vision is only required by a pipeline that hands the model page
            # images; one that reads OCR text is better off without it.
            if requires_vision(chosen_pipeline) and not chosen.vision:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"'{chosen_pipeline.name}' sends page images to the model, and "
                        f"{settings.model} has no vision. Pick a vision model, or a "
                        "pipeline that reads text."
                    ),
                )
    def merged(latest: AppSettings) -> AppSettings:
        # The model list was awaited above. The catalog and the key are
        # taken from the settings as they are now, so a processor saved or a
        # key cleared in the meantime is not reverted by this form.
        gemini = (
            settings.gemini
            if settings.gemini.api_key != previous_settings.gemini.api_key
            else settings.gemini.model_copy(update={"api_key": latest.gemini.api_key})
        )
        return settings.model_copy(
            update={
                "gemini": gemini,
                "gcp": settings.gcp.model_copy(update={"processors": latest.gcp.processors}),
            }
        )

    saved = deps.settings_store.update(merged)
    previous_schema = [
        (entity.name, entity.format) for entity in previous_settings.prompts.entities
    ]
    new_schema = [(entity.name, entity.format) for entity in saved.prompts.entities]
    if (
        previous_schema != new_schema
        and deps.model_runtime_states.get(saved.model) == "ready"
        and deps.model_warmup_modes.get(saved.model) == "vision_and_schema"
    ):
        deps.model_runtime_states[saved.model] = "loaded"
    if (
        requires_vision(chosen_pipeline)
        and deps.model_runtime_states.get(saved.model) == "ready"
        and deps.model_warmup_modes.get(saved.model) == "schema"
    ):
        # A model prepared behind OCR has never seen an image. Switching to a
        # vision pipeline must expose Warm up instead of charging projector
        # startup (or its failure) to the first document.
        deps.model_runtime_states[saved.model] = "loaded"
    return deps.masked(saved)


@router.get("/api/settings/gcp", response_model=GcpKeyStatus)
async def gcp_key_status() -> GcpKeyStatus:
    """What the backend can say about the key file, and never its contents."""
    return deps.gcp_status(deps.settings_store.read())


@router.post("/api/settings/gcp/verify", response_model=GcpKeyStatus)
async def verify_gcp_key() -> GcpKeyStatus:
    """Send one blank page to each configured processor and report who answered.

    A real call, because a key that parses is not a key that is allowed to use
    these processors. It costs one page per processor.
    """
    settings = deps.settings_store.read()
    status = deps.gcp_status(settings)
    if not status.configured:
        return status

    client = DocumentAiClient(
        deps.GCP_CREDENTIALS_PATH, settings.gcp.project_id, settings.gcp.location
    )
    configured = [
        ("OCR", settings.gcp.ocr_processor_id),
        ("Layout Parser", settings.gcp.layout_processor_id),
    ]
    verified: list[str] = []
    problems: list[str] = []
    probe = deps.blank_page_pdf()
    for label, processor_id in configured:
        if not processor_id.strip():
            problems.append(f"No {label} processor id is configured.")
            continue
        try:
            await client.process(processor_id, probe)
            verified.append(processor_id)
        except DocumentAiError as exc:
            problems.append(str(exc))

    return status.model_copy(
        update={"verified_processors": verified, "problem": " ".join(problems)}
    )
