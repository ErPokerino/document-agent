"""Recorded runs."""

import asyncio
from dataclasses import asdict
from typing import Annotated

from fastapi import HTTPException, Query, Response, APIRouter

from app.api import deps
from app.domain.models import CorrectionsRequest, ExtractionRun, ExtractionRunDetail
from app.domain.billing import UsageDetail
from app.pipeline.steps import render_page_png

router = APIRouter()


def run_usage(run_id: int):
    from app.services.billing import UsageStore
    detail = UsageStore(deps.DATABASE_PATH).detail(run_id=run_id)
    return detail.cost if detail.records else None


@router.get("/api/runs/{run_id}/usage", response_model=UsageDetail)
async def get_run_usage(run_id: int):
    from app.services.billing import UsageStore
    if deps.run_store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return UsageStore(deps.DATABASE_PATH).detail(run_id=run_id)


@router.get("/api/runs", response_model=list[ExtractionRun])
async def list_runs(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    validated_only: bool = False,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> list[ExtractionRun]:
    return [
        ExtractionRun(**asdict(run), cost=run_usage(run.id))
        for run in deps.run_store.list_runs(limit=limit, validated_only=validated_only, before_id=before_id)
    ]


@router.get("/api/runs/{run_id}/pages/{page}.png", response_class=Response)
async def run_page_image(run_id: int, page: int) -> Response:
    """One page of a run's document, rendered.

    Highlighting needs a surface with known coordinates, and the browser's PDF
    viewer is not one: nothing outside it can know where it put the page. An
    image can be overlaid exactly, and the app already renders pages.
    """
    detail = deps.run_store.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    content = deps.run_store.read_document(detail.file_sha256)
    if content is None:
        raise HTTPException(status_code=404, detail="That run's document is no longer stored.")

    rendered = await asyncio.to_thread(render_page_png, content, page, 2)
    if rendered is None:
        raise HTTPException(status_code=404, detail=f"That document has no page {page + 1}")

    return Response(
        content=rendered,
        media_type="image/png",
        # Addressed by run and page, and a run's document never changes.
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/api/runs/{run_id}", response_model=ExtractionRunDetail)
async def get_run(run_id: int) -> ExtractionRunDetail:
    run = deps.run_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No run with id {run_id}")
    return ExtractionRunDetail(**asdict(run), cost=run_usage(run.id))


@router.post("/api/runs/{run_id}/corrections", status_code=204, response_class=Response)
async def record_corrections(run_id: int, request: CorrectionsRequest) -> Response:
    try:
        deps.run_store.record_corrections(run_id, request.corrections)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
