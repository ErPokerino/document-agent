"""Explicit, synthetic live check run as the deployed service identity.

Run with `python -m app.services.model_garden_smoke`. No user documents or
settings are modified. Provider failures are reported individually so that
one missing quota does not conceal another working model.
"""

import asyncio
import json
from datetime import datetime, timezone

from app.domain.billing import UsageRecord
from app.domain.models import EntityDefinition, ModelGardenSettings, PromptConfiguration
from app.services.billing import account
from app.services.model_garden import ModelGardenClient, PARTNER_MODELS


async def main() -> None:
    prompts = PromptConfiguration(entities=[EntityDefinition(name="invoice_number", format="text", description="Invoice number")])
    for model in PARTNER_MODELS:
        client = ModelGardenClient(ModelGardenSettings(max_output_tokens=1024))
        try:
            result = await client.extract_entities(model.id, [], prompts, "1", 1, 1,
                document_text="SYNTHETIC TEST INVOICE. Invoice number: TEST-2026-001. No personal data.")
            status = "ok" if result["invoice_number"].value == "TEST-2026-001" else "unexpected value"
        except Exception as exc:
            status = str(exc)
        record = account(UsageRecord(id="smoke", group_id="smoke", created_at=datetime.now(timezone.utc).isoformat(),
            model=model.id, provider="model_garden", publisher=model.publisher,
            location="eu" if model.publisher == "anthropic" else "global", step="synthetic_smoke",
            document="synthetic", status=status), client.last_usage or {}, client.http_status)
        print(json.dumps({"model": model.id, "status": status, "http_status": client.http_status,
                          "usage": client.last_usage, "cost": record.cost.model_dump()}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
