"""Pipelines: what can go into one, and the saved ones."""

from fastapi import HTTPException, Response, APIRouter

from app.api import deps
from app.domain.models import PipelineRenameRequest, SavedPipeline, StepCatalogueEntry
from app.pipeline.definition import CONTRACTS, PipelineDefinition
from app.pipeline.store import InvalidPipelineName, UnknownPipeline

router = APIRouter()


@router.get("/api/pipelines/steps", response_model=list[StepCatalogueEntry])
async def list_pipeline_steps() -> list[StepCatalogueEntry]:
    """What can go into a pipeline, and what each piece needs and leaves behind."""
    return [
        StepCatalogueEntry(
            kind=contract.kind.value,
            label=contract.label,
            description=contract.description,
            requires_all=[artifact.value for artifact in contract.requires_all],
            requires_any=[artifact.value for artifact in contract.requires_any],
            produces=[artifact.value for artifact in contract.produces],
        )
        for contract in CONTRACTS.values()
    ]


@router.get("/api/pipelines", response_model=list[SavedPipeline])
async def list_pipelines() -> list[SavedPipeline]:
    return [deps.saved_pipeline(definition) for definition in deps.pipeline_store.list()]


@router.post("/api/pipelines/check", response_model=SavedPipeline)
async def check_pipeline(definition: PipelineDefinition) -> SavedPipeline:
    """Say what is wrong with a pipeline someone is still editing. Saves nothing."""
    return deps.saved_pipeline(definition)


@router.get("/api/pipelines/{name}", response_model=SavedPipeline)
async def get_pipeline(name: str) -> SavedPipeline:
    try:
        return deps.saved_pipeline(deps.pipeline_store.read(name))
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownPipeline as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/api/pipelines/{name}", response_model=SavedPipeline)
async def save_pipeline(name: str, definition: PipelineDefinition) -> SavedPipeline:
    if name != definition.name:
        raise HTTPException(
            status_code=400,
            detail=f"This pipeline is saved as {name!r}; rename it in the body to move it.",
        )
    deps.refuse_unusable(definition)
    try:
        return deps.saved_pipeline(deps.pipeline_store.save(definition))
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/pipelines/{name}", response_model=SavedPipeline)
async def rename_pipeline(name: str, request: PipelineRenameRequest) -> SavedPipeline:
    """Rename in place, carrying the selection with it.

    A rename that quietly left the app running the old name would be worse than
    refusing one, so the setting follows the file.
    """
    try:
        renamed = deps.pipeline_store.rename(name, request.name)
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownPipeline as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    deps.settings_store.update(
        lambda latest: latest.model_copy(update={"pipeline": renamed.name})
        if latest.pipeline == name
        else latest
    )
    return deps.saved_pipeline(renamed)


@router.delete("/api/pipelines/{name}", status_code=204, response_class=Response)
async def delete_pipeline(name: str) -> Response:
    if deps.settings_store.read().pipeline == name:
        raise HTTPException(
            status_code=409,
            detail="That pipeline is in use. Select another one in Pipelines before deleting it.",
        )
    try:
        deps.pipeline_store.delete(name)
    except InvalidPipelineName as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnknownPipeline as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
