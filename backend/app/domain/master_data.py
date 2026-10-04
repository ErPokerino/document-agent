"""Reference tables and the corrections written for one supplier."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SupplierRuleModel(BaseModel):
    """A correction written for one supplier's documents.

    Keyed on the register id, never the name: several spellings of one supplier
    resolve to the same id, and the id is what is either right or wrong.
    """

    id: int | None = None
    id_subject: str
    entity: str
    kind: Literal["fixed", "regex", "prompt"]
    value: str = ""
    pattern: str = ""
    prompt: str = ""
    note: str = ""


class SupplierRuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id_subject: str
    entity: str
    kind: Literal["fixed", "regex", "prompt"]
    value: str = ""
    pattern: str = ""
    prompt: str = ""
    note: str = ""


class SupplierRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str | None = None
    kind: Literal["fixed", "regex", "prompt"] | None = None
    value: str | None = None
    pattern: str | None = None
    prompt: str | None = None
    note: str | None = None


class MasterDataImport(BaseModel):
    """What an import did, row by row where it did not."""

    added: int
    skipped: int
    reasons: list[str] = Field(default_factory=list)


class MasterDataColumn(BaseModel):
    key: str
    label: str
    hint: str
    kind: Literal["identifier", "text", "timestamp"]
    editable: bool
    # Filled in automatically when a row is created; still editable afterwards.
    generated: bool = False


class MasterDataTable(BaseModel):
    key: str
    label: str
    description: str
    id_column: str
    seed_entity: str
    match_column: str
    columns: list[MasterDataColumn]


class MasterDataRowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, str]
