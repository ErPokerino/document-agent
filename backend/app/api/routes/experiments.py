"""Lab experiments: a grid of pipelines and models over one dataset, run as ordinary runs."""

import asyncio
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from app.api import deps
from app.api.routes.evaluations import prepare_evaluation, run_recorded_evaluation
from app.domain.models import (
    Experiment,
    ExperimentCell,
    ExperimentComparison,
    ExperimentRequest,
)
from app.evaluation.experiments import Cell, ModelChoice, compare, execution_order, plan_cells
from app.pipeline.definition import describe_problems, requires_vision, uses_model
from app.pipeline.store import InvalidPipelineName, UnknownPipeline
from app.services.document_ai import DocumentAiError
from app.services.gemini import GeminiError, find_model
from app.services.lm_studio import LMStudioError

router = APIRouter()


def _cell_status(cell: Cell, run: Any) -> str:
    if cell.skipped:
        return "skipped"
    if cell.phase in ("loading",):
        return "loading"
    if run is not None:
        return run.status
    if cell.error:
        return "error"
    return "pending"


def _experiment(stored: Any, *, with_comparison: bool) -> Experiment:
    runs = {run.experiment_cell: run for run in deps.evaluation_store.experiment_runs(stored.id)}
    cells = [
        ExperimentCell(
            index=index, pipeline=cell.pipeline, provider=cell.provider, model=cell.model,  # type: ignore[arg-type]
            status=_cell_status(cell, runs.get(index)), skipped=cell.skipped, error=cell.error,
            run=deps.evaluation_model(runs[index]) if index in runs else None,
        )
        for index, cell in enumerate(stored.cells)
    ]
    comparison = None
    if with_comparison:
        finished = {
            index: deps.evaluation_store.get_evaluation(run.id)
            for index, run in runs.items()
            if run.status != "running"
        }
        result = compare(finished)
        if result is not None:
            comparison = ExperimentComparison(
                shared_documents=result.shared_documents, left_out=result.left_out,
                resamples=result.resamples, cells=[asdict(score) for score in result.cells],
            )
    return Experiment(
        id=stored.id, name=stored.name, created_at=stored.created_at, finished_at=stored.finished_at,
        dataset=stored.dataset, status=stored.status, reuse_readings=stored.reuse_readings, error=stored.error,
        cells=cells, comparison=comparison,
    )


@router.get("/api/experiments", response_model=list[Experiment])
async def list_experiments() -> list[Experiment]:
    return [_experiment(stored, with_comparison=False) for stored in deps.experiment_store.list()]


@router.get("/api/experiments/{experiment_id}", response_model=Experiment)
async def get_experiment(experiment_id: int) -> Experiment:
    stored = deps.experiment_store.get(experiment_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No experiment with id {experiment_id}")
    return _experiment(stored, with_comparison=True)


@router.delete("/api/experiments/{experiment_id}", status_code=204, response_class=Response)
async def delete_experiment(experiment_id: int) -> Response:
    """Forget the grid. Its runs stay in Past runs, where each one is an ordinary run."""
    stored = deps.experiment_store.get(experiment_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No experiment with id {experiment_id}")
    if stored.status == "running":
        raise HTTPException(status_code=409, detail="Cancel that experiment before deleting it.")
    deps.experiment_store.delete(experiment_id)
    return Response(status_code=204)


@router.post("/api/experiments/{experiment_id}/cancel", response_model=Experiment, status_code=202)
async def cancel_experiment(experiment_id: int) -> Experiment:
    stored = deps.experiment_store.get(experiment_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No experiment with id {experiment_id}")
    if stored.status != "running":
        raise HTTPException(status_code=409, detail="That experiment is not running.")
    deps.experiment_store.finish(experiment_id, "cancelled")
    for run in deps.evaluation_store.experiment_runs(experiment_id):
        if run.status == "running":
            deps.evaluation_store.finish(run.id, "cancelled")
    deps.cancel_job("experiment", experiment_id)
    return _experiment(deps.experiment_store.get(experiment_id), with_comparison=False)


@router.post("/api/experiments", response_model=Experiment, status_code=202)
async def start_experiment(request: ExperimentRequest) -> Experiment:
    deps.require_dataset(request.dataset)
    settings = deps.settings_store.read()

    definitions = []
    for name in dict.fromkeys(request.pipelines):
        try:
            definition = deps.pipeline_store.read(name)
        except (UnknownPipeline, InvalidPipelineName) as exc:
            raise HTTPException(status_code=404, detail=f"No pipeline named {name}") from exc
        problems = describe_problems(definition)
        if problems:
            raise HTTPException(status_code=400, detail=f"The pipeline '{name}' cannot run: {' '.join(problems)}")
        definitions.append(definition)

    choices = []
    local = None
    for choice in {(c.provider, c.model): c for c in request.models}.values():
        if choice.provider == "gemini":
            if find_model(choice.model) is None:
                raise HTTPException(status_code=400, detail=f"{choice.model} is not one of the supported hosted models.")
            if not deps.gemini_available(settings):
                raise HTTPException(status_code=409, detail="No Gemini API key is configured. Add one in LLM.")
            choices.append(ModelChoice("gemini", choice.model, vision=True))
            continue
        if choice.provider == "model_server":
            try:
                served = {model.id: model for model in await deps.ModelServerClient().list_models()}
            except LMStudioError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            if choice.model not in served:
                raise HTTPException(status_code=400, detail=f"The model server does not serve {choice.model}.")
            # A model whose capabilities were not reported is not assumed blind.
            found = served[choice.model]
            choices.append(ModelChoice("model_server", choice.model, vision=found.vision or not found.capabilities_known))
            continue
        if local is None:
            try:
                local = {model.id: model for model in await deps.LMStudioClient(settings.lm_studio_url).list_models()}
            except LMStudioError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        found = local.get(choice.model)
        if found is None:
            raise HTTPException(status_code=400, detail=f"{choice.model} is not installed in LM Studio on this machine.")
        # A model whose capabilities were not reported is not assumed blind.
        choices.append(ModelChoice("lm_studio", choice.model, vision=found.vision or not found.capabilities_known))

    if not choices and any(uses_model(definition) for definition in definitions):
        raise HTTPException(status_code=400, detail="A chosen pipeline calls a model, and no model is chosen.")
    cells = plan_cells(definitions, choices)
    if not execution_order(cells):
        raise HTTPException(status_code=400, detail="Every cell of this experiment is skipped, so there is nothing to run.")
    needs_model = [cell for cell in cells if cell.skipped is None and cell.provider != "none"]

    name = request.name.strip() or f"{len(definitions)} pipeline{'s' if len(definitions) != 1 else ''} × {len(choices)} model{'s' if len(choices) != 1 else ''} on {request.dataset}"
    deps.claim_lab()
    try:
        experiment_id = deps.experiment_store.create(name=name, dataset=request.dataset, cells=cells, reuse_readings=request.reuse_readings)
    except Exception:
        deps.release_lab()
        raise
    # A model is warmed with an image when any pipeline it serves in this
    # experiment sends images; some models answer text and die on an image.
    by_name = {definition.name: definition for definition in definitions}
    vision_for: dict[str, bool] = {}
    for cell in needs_model:
        vision_for[cell.model] = vision_for.get(cell.model, False) or requires_vision(by_name[cell.pipeline])
    try:
        await deps.start_job(
            "experiment", name,
            {"experiment_id": experiment_id, "dataset": request.dataset, "reuse_readings": request.reuse_readings, "vision_for": vision_for},
            subject_id=experiment_id,
        )
    except Exception as exc:
        deps.experiment_store.finish(experiment_id, "failed", error=str(exc))
        deps.release_lab()
        raise
    return _experiment(deps.experiment_store.get(experiment_id), with_comparison=False)


async def run_experiment_job(job: Any, cancelled: asyncio.Event) -> None:
    """The work of an `experiment` job: every cell, one ordinary Lab run after another.

    Cells are grouped by model, so each local model is loaded once. Today's
    settings are read when the work starts, which is when the experiment's
    runs record them.
    """
    experiment_id = int(job.payload["experiment_id"])
    dataset = str(job.payload["dataset"])
    reuse_readings = bool(job.payload.get("reuse_readings"))
    vision_for: dict[str, bool] = job.payload.get("vision_for") or {}
    try:
        stored = deps.experiment_store.get(experiment_id)
        if stored is None:
            raise ValueError(f"No experiment with id {experiment_id}")
        cells = stored.cells
        settings = deps.settings_store.read()
        for index in execution_order(cells):
            if cancelled.is_set() or deps.experiment_store.get(experiment_id).status != "running":
                break
            cell = cells[index]
            cell_settings = settings.model_copy(update={"pipeline": cell.pipeline})
            if cell.provider != "none":
                cell_settings = cell_settings.model_copy(update={"provider": cell.provider, "model": cell.model})
            try:
                if cell.provider == "lm_studio" and deps.model_runtime_states.get(cell.model) != "ready":
                    deps.experiment_store.update_cell(experiment_id, index, phase="loading")
                    await deps.load_local_model(cell_settings, cell.model, warm_vision=vision_for.get(cell.model, False), phase="evaluating")
                if cell.provider == "model_server":
                    # The server holds one model at a time; cells are grouped by
                    # model, so each is loaded once, as with LM Studio.
                    served = {model.id: model for model in await deps.ModelServerClient().list_models()}
                    if not (served.get(cell.model) and served[cell.model].ready):
                        deps.experiment_store.update_cell(experiment_id, index, phase="loading")
                        await deps.load_served_model(cell_settings, cell.model, warm_vision=vision_for.get(cell.model, False), phase="evaluating")
                deps.experiment_store.update_cell(experiment_id, index, phase="running")
                evaluation_id = await prepare_evaluation(
                    dataset, cell_settings, reuse_readings=reuse_readings, claim=False,
                    experiment_id=experiment_id, experiment_cell=index,
                )
                await run_recorded_evaluation(evaluation_id, cancelled, resumed=False)
            except HTTPException as exc:
                deps.experiment_store.update_cell(experiment_id, index, error=str(exc.detail))
            except (LMStudioError, GeminiError, DocumentAiError, ValueError, OSError) as exc:
                deps.experiment_store.update_cell(experiment_id, index, error=str(exc))
            finally:
                deps.experiment_store.update_cell(experiment_id, index, phase=None)
        deps.experiment_store.finish(experiment_id, "cancelled" if cancelled.is_set() else "completed")
    except asyncio.CancelledError:
        deps.experiment_store.finish(experiment_id, "cancelled")
        raise
    except Exception as exc:
        deps.experiment_store.finish(experiment_id, "failed", error=str(exc))
        raise
    finally:
        deps.release_lab()
