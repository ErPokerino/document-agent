"""Versioned Model Garden tariffs and durable, per-attempt accounting.

No document content, prompts, credentials or full responses are stored here.
Only the provider's usage object and the price used at the time of the call.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from app.domain.billing import CostSummary, UsageDetail, UsageRecord
from app.services import db
from app.services.errors import ProviderError
from app.services.extraction_provider import ExtractionProvider

SOURCE = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
CHECKED_ON = "2026-10-06"
SCHEMA = """
CREATE TABLE IF NOT EXISTS model_usage (
    id TEXT PRIMARY KEY, group_id TEXT NOT NULL, evaluation_id INTEGER,
    run_id INTEGER, started REAL NOT NULL, scope TEXT NOT NULL, record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS model_usage_evaluation ON model_usage(evaluation_id);
CREATE INDEX IF NOT EXISTS model_usage_run ON model_usage(run_id);
CREATE INDEX IF NOT EXISTS model_usage_scope ON model_usage(scope, started);
"""


def tariff(model: str, location: str, context: int = 0) -> dict[str, Any]:
    """USD per million tokens. A tier applies to the entire request."""
    regional = location != "global"
    if model.startswith("claude-sonnet"):
        rates = (2.2, 11, .22, 2.75, 4.4) if regional else (2, 10, .2, 2.5, 4)
    elif model.startswith("claude-opus"):
        rates = (4.4, 22, .22, 5.5, 8.8) if regional else (4, 20, .2, 5, 8)
    elif model == "grok-4.7":
        rates = (4, 12, 1, None, None) if context > 200000 else (2, 6, .5, None, None)
    else:
        return {}
    if model.startswith("claude") and context > 200000:
        # The published long-context cache cells are blank. Do not infer them.
        rates = (rates[0], rates[1], None, None, None)
    return dict(zip(("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"), rates)) | {
        "source": SOURCE, "checked_on": CHECKED_ON, "version": "2026-10-06",
        "currency": "USD", "location": location, "context_tier": ">200k" if context > 200000 else "<=200k",
    }


def account(record: UsageRecord, raw: dict[str, Any], http_status: int | None) -> UsageRecord:
    """Preserve missing usage as unknown and do not count reasoning twice."""
    record.raw_usage, record.http_status = raw, http_status
    if http_status is not None and 400 <= http_status <= 599:
        record.input_tokens = record.output_tokens = 0
        record.cost = CostSummary(status="complete", total_usd=0, calls=1, source=SOURCE, checked_on=CHECKED_ON)
        return record
    if record.publisher == "anthropic":
        record.input_tokens = raw.get("input_tokens")
        record.output_tokens = raw.get("output_tokens")
        record.cached_tokens = raw.get("cache_read_input_tokens", 0)
        creation = raw.get("cache_creation") or {}
        record.cache_write_1h_tokens = creation.get("ephemeral_1h_input_tokens", 0)
        record.cache_write_5m_tokens = creation.get("ephemeral_5m_input_tokens", 0)
        # Without a TTL breakdown, a cache write cannot be priced truthfully.
        unidentified_writes = raw.get("cache_creation_input_tokens", 0) - record.cache_write_1h_tokens - record.cache_write_5m_tokens
        context = (record.input_tokens or 0) + record.cached_tokens + raw.get("cache_creation_input_tokens", 0)
    else:
        from app.services.model_garden import grok_output_tokens
        record.input_tokens = raw.get("prompt_tokens")
        record.output_tokens = grok_output_tokens(raw)
        record.cached_tokens = (raw.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        record.reasoning_tokens = (raw.get("completion_tokens_details") or {}).get("reasoning_tokens")
        context = record.input_tokens or 0
        if record.input_tokens is not None:
            record.input_tokens -= record.cached_tokens
        unidentified_writes = 0
    # The tier is based on all input, including cache reads and cache writes.
    reserved_output = record.tariff.get("reserved_output")
    record.tariff = tariff(record.model, record.location or "global", context)
    if reserved_output is not None:
        record.tariff["reserved_output"] = reserved_output
    complete = http_status == 200 and record.input_tokens is not None and record.output_tokens is not None and not unidentified_writes
    counts = (record.input_tokens, record.output_tokens, record.cached_tokens,
              record.cache_write_5m_tokens, record.cache_write_1h_tokens)
    known = Decimal(0)
    for count, category in zip(counts, ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")):
        rate = record.tariff.get(category)
        if count is not None and count > 0:
            if rate is None:
                complete = False
            else:
                known += Decimal(str(count)) * Decimal(str(rate)) / Decimal(1000000)
        if count is not None and count < 0:
            complete = False
    record.cost = CostSummary(status="complete" if complete else "partial" if known else "unknown",
                              total_usd=float(known) if complete else None, known_usd=float(known), calls=1,
                              source=SOURCE, checked_on=CHECKED_ON)
    return record


def summarize(records: list[UsageRecord]) -> CostSummary:
    if not records:
        return CostSummary(source=SOURCE, checked_on=CHECKED_ON)
    known = sum(Decimal(str(record.cost.known_usd)) for record in records)
    complete = all(record.cost.status == "complete" for record in records)
    return CostSummary(status="complete" if complete else "partial" if known else "unknown",
                       total_usd=float(known) if complete else None, known_usd=float(known),
                       calls=len(records), source=SOURCE, checked_on=CHECKED_ON)


class UsageStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        db.prepare(path)
        with db.connect(path) as connection:
            db.execute_script(connection, SCHEMA)

    def save(self, record: UsageRecord, scope: str, *, started: float | None = None) -> None:
        with db.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO model_usage (id, group_id, evaluation_id, run_id, started, scope, record_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET record_json=excluded.record_json",
                (record.id, record.group_id, record.evaluation_id, record.run_id, started or time.time(), scope, record.model_dump_json()),
            )

    def bind_run(self, group: str, run_id: int) -> None:
        with db.connect(self.path) as connection:
            connection.execute("UPDATE model_usage SET run_id=? WHERE group_id=?", (run_id, group))

    @staticmethod
    def read(connection: Any, *, evaluation_id: int | None = None, run_id: int | None = None,
             group_id: str | None = None) -> UsageDetail:
        column, value = ("evaluation_id", evaluation_id) if evaluation_id is not None else ("run_id", run_id) if run_id is not None else ("group_id", group_id)
        rows = connection.execute(f"SELECT record_json, evaluation_id, run_id FROM model_usage WHERE {column}=? ORDER BY started, id", (value,)).fetchall()
        records = [UsageRecord.model_validate_json(row["record_json"]).model_copy(update={"evaluation_id": row["evaluation_id"], "run_id": row["run_id"]}) for row in rows]
        return UsageDetail(cost=summarize(records), records=records)

    def detail(self, **scope: Any) -> UsageDetail:
        with db.connect(self.path) as connection:
            return self.read(connection, **scope)

    def reserve_grok(self, record: UsageRecord, scope: str, maximum_output: int) -> float:
        """Serialize reservations across API and workers, on SQLite and PostgreSQL.

        Limits are the project's observed global quotas, configurable for another
        deployment. Pending calls reserve their entire output budget for 60s.
        """
        import os
        rpm = int(os.getenv("DOCUFLOW_GROK_RPM", "10"))
        output_tpm = int(os.getenv("DOCUFLOW_GROK_OUTPUT_TPM", "10500"))
        input_tpm = int(os.getenv("DOCUFLOW_GROK_INPUT_TPM", "1135000"))
        if maximum_output > output_tpm:
            raise ProviderError("The output budget exceeds the configured Grok token quota.")
        now = time.time()
        with db.connect(self.path) as connection:
            if isinstance(connection, db.PostgresConnection):
                connection.execute("SELECT pg_advisory_xact_lock(7047427)")
            else:
                connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT started, record_json FROM model_usage WHERE scope=? AND started>? ORDER BY started", (scope, now - 60)).fetchall()
            recent = [UsageRecord.model_validate_json(row["record_json"]) for row in rows]
            used_output = sum((item.output_tokens if item.output_tokens is not None else item.tariff.get("reserved_output", 0)) for item in recent)
            used_input = sum((item.input_tokens or 0) + item.cached_tokens for item in recent)
            if len(rows) >= rpm or used_output + maximum_output > output_tpm or used_input >= input_tpm:
                return max(.1, 60 - (now - rows[0]["started"]))
            record.tariff["reserved_output"] = maximum_output
            connection.execute("INSERT INTO model_usage (id, group_id, evaluation_id, run_id, started, scope, record_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (record.id, record.group_id, record.evaluation_id, record.run_id, now, scope, record.model_dump_json()))
            return 0


class MeteredProvider(ExtractionProvider):
    """Record each partner attempt even when parsing or validation fails."""
    def __init__(self, client: ExtractionProvider, context: Any) -> None:
        self.client, self.context = client, context
        self.last_prediction_stats = None

    async def extract_entities(self, model: str, images: list[str], prompts: Any, page_range: str,
                               total_pages: int, processed_pages: int, document_text: str = "") -> Any:
        from app.services.model_garden import connection, find_partner
        context = self.context
        selected = find_partner(model)
        assert selected is not None
        project, location = connection(model, context.model_garden_settings)
        project = context.model_garden_project or project
        location = context.model_garden_location or location
        scope = f"{project}/{location}/{model}"
        for attempt in range(3):
            record = UsageRecord(id=str(uuid4()), group_id=context.usage_group,
                created_at=datetime.now(timezone.utc).isoformat(), model=model, provider="model_garden",
                publisher=selected.publisher, project=project, location=location,
                step=context.current_step, document=context.filename, evaluation_id=context.evaluation_id,
                status="pending", tariff=tariff(model, location))
            if selected.publisher == "xai":
                while True:
                    delay = await asyncio.to_thread(context.usage_store.reserve_grok, record, scope, context.model_garden_settings.grok_max_output_tokens)
                    if not delay:
                        break
                    await asyncio.sleep(min(delay, 5))
            else:
                await asyncio.to_thread(context.usage_store.save, record, scope)
            retry = False
            try:
                result = await self.client.extract_entities(model, images, prompts, page_range, total_pages, processed_pages, document_text)
                record.status = "succeeded"
                return result
            except ProviderError:
                record.status = "failed"
                retry = getattr(self.client, "http_status", None) in (429, 503) and attempt < 2
                if not retry:
                    raise
            except BaseException:
                record.status = "cancelled" if asyncio.current_task().cancelling() else "failed"
                raise
            finally:
                record.request_id = getattr(self.client, "request_id", None)
                account(record, getattr(self.client, "last_usage", None) or {}, getattr(self.client, "http_status", None))
                # A disconnect cannot discard an already billed response.
                context.usage_store.save(record, scope)
                self.last_prediction_stats = self.client.last_prediction_stats
            if retry:
                await asyncio.sleep(max(2 ** attempt, getattr(self.client, "retry_after", 1)))


def record_pages(context: Any, before: dict[str, int], failed: bool) -> None:
    """Snapshot Document AI charges in partner runs, alongside model charges."""
    kind = context.current_step.split(" #", 1)[0]
    pages = (context.artifacts.get("document_ai_pages") or {}).get(kind, 0) - before.get(kind, 0)
    if not pages and not failed:
        return  # A reused reading makes no billable request.
    rates = {"document_ai_ocr": "ocr_per_thousand_pages", "document_ai_layout": "layout_per_thousand_pages",
             "document_ai_extract": "custom_extractor_per_thousand_pages"}
    rate = getattr(context.page_pricing, rates.get(kind, ""), None)
    complete = not failed and rate is not None
    amount = float(Decimal(pages) * Decimal(str(rate)) / 1000) if rate is not None else 0
    record = UsageRecord(id=str(uuid4()), group_id=context.usage_group,
        created_at=datetime.now(timezone.utc).isoformat(), model=kind, provider="document_ai", publisher="google",
        step=context.current_step, document=context.filename, evaluation_id=context.evaluation_id,
        status="failed" if failed else "succeeded", raw_usage={"pages": pages},
        tariff={"per_thousand_pages": rate, "checked_on": context.page_pricing.pricing_checked_on},
        cost=CostSummary(status="complete" if complete else "partial" if amount else "unknown",
                         total_usd=amount if complete else None, known_usd=amount, calls=1))
    context.usage_store.save(record, "document_ai")
