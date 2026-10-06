"""Recorded usage and the tariff applied when a request ran."""

from typing import Any, Literal
from pydantic import BaseModel, Field


class CostSummary(BaseModel):
    status: Literal["complete", "partial", "unknown"] = "unknown"
    currency: Literal["USD"] = "USD"
    total_usd: float | None = None
    known_usd: float = 0
    calls: int = 0
    source: str | None = None
    checked_on: str | None = None


class UsageRecord(BaseModel):
    id: str
    group_id: str
    created_at: str
    model: str
    provider: str
    publisher: str | None = None
    project: str | None = None
    location: str | None = None
    step: str
    document: str
    evaluation_id: int | None = None
    run_id: int | None = None
    status: str
    http_status: int | None = None
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    reasoning_tokens: int | None = None
    raw_usage: dict[str, Any] = Field(default_factory=dict)
    tariff: dict[str, Any] = Field(default_factory=dict)
    cost: CostSummary = Field(default_factory=CostSummary)


class UsageDetail(BaseModel):
    cost: CostSummary
    records: list[UsageRecord]
