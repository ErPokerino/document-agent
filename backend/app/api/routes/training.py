"""Models: what is learned from the datasets, and the readings it learns from."""

from fastapi import APIRouter, Response

from app.api import deps
from app.domain.models import ReadingCacheStatus

router = APIRouter()


@router.get("/api/reading-cache", response_model=ReadingCacheStatus)
async def reading_cache_status() -> ReadingCacheStatus:
    stats = deps.reading_cache.stats()
    return ReadingCacheStatus(entries=stats.entries, size_bytes=stats.size_bytes)


@router.delete("/api/reading-cache", status_code=204, response_class=Response)
async def clear_reading_cache() -> Response:
    deps.reading_cache.clear()
    return Response(status_code=204)
