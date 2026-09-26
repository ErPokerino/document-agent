"""A stable identity for one Lab configuration.

Two runs share a fingerprint when they used the same documents, labels,
prompts, pipeline, model profile, register rows and supplier rules. The hash
is of the canonical JSON of those inputs, so a later edit to the register is
a different experiment even when the pipeline name is unchanged.
"""

import hashlib
import json
from typing import Any

from app.domain.models import ModelExecutionProfile, PromptConfiguration
from app.pipeline.definition import PipelineDefinition
from app.services.supplier_rules import SupplierRule


def rule_record(rule: SupplierRule) -> dict[str, str]:
    """The rule as it applies, without the database id that would change if it were recreated."""
    return {
        "id_subject": rule.id_subject,
        "entity": rule.entity,
        "kind": rule.kind,
        "value": rule.value,
        "pattern": rule.pattern,
        "prompt": rule.prompt,
        "note": rule.note,
    }


def rules_from_records(records: list[dict[str, Any]]) -> list[SupplierRule]:
    return [
        SupplierRule(
            id_subject=str(record["id_subject"]),
            entity=str(record["entity"]),
            kind=str(record["kind"]),
            value=str(record.get("value") or ""),
            pattern=str(record.get("pattern") or ""),
            prompt=str(record.get("prompt") or ""),
            note=str(record.get("note") or ""),
        )
        for record in records
    ]


def configuration_fingerprint(
    *,
    dataset_snapshot: dict[str, Any],
    prompts: PromptConfiguration,
    pipeline: PipelineDefinition,
    execution_profile: ModelExecutionProfile | None,
    register_rows: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> str:
    inputs = [
        {"name": name, "sha256": entry["sha256"], "labels": entry["labels"]}
        for name, entry in sorted(dataset_snapshot.items())
    ]
    payload = {
        "inputs": inputs,
        "prompts": prompts.model_dump(mode="json"),
        "pipeline": pipeline.model_dump(mode="json"),
        "execution_profile": (
            execution_profile.model_dump(mode="json") if execution_profile is not None else None
        ),
        "register": register_rows,
        "rules": rules,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
