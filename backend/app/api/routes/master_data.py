"""The register, and the supplier rules that key on it."""

from typing import Annotated, Any

from fastapi import File, HTTPException, Query, Response, UploadFile, APIRouter

from app.api import deps
from app.domain.models import (
    MasterDataColumn,
    MasterDataRowRequest,
    MasterDataImport,
    SupplierRuleModel,
    SupplierRuleRequest,
    SupplierRuleUpdate,
    MasterDataTable,
)
from app.services.master_data import TABLES, DuplicateRow, UnknownRow, UnknownTable
from app.services.master_data_csv import csv_to_rows, rows_to_csv
from app.services.spreadsheet import decode as decode_spreadsheet
from app.services.supplier_rules import SupplierRule

router = APIRouter()


@router.get("/api/master-data/tables", response_model=list[MasterDataTable])
async def list_master_data_tables() -> list[MasterDataTable]:
    """What tables exist and what each column is, so the UI needs no copy of it."""
    return [
        MasterDataTable(
            key=table.key,
            label=table.label,
            description=table.description,
            id_column=table.id_column,
            seed_entity=table.seed_entity,
            match_column=table.match_column,
            columns=[
                MasterDataColumn(
                    key=column.key,
                    label=column.label,
                    hint=column.hint,
                    kind=column.kind,
                    editable=column.editable,
                    generated=column.generated,
                )
                for column in table.columns
            ],
        )
        for table in TABLES.values()
    ]


@router.get("/api/supplier-rules", response_model=list[SupplierRuleModel])
async def list_supplier_rules(id_subject: str = "") -> list[SupplierRuleModel]:
    """Every rule, or the ones written for one supplier."""
    rules = (
        deps.supplier_rule_store.for_supplier(id_subject.strip())
        if id_subject.strip()
        else deps.supplier_rule_store.all()
    )
    return [deps.rule_model(rule) for rule in rules]


@router.post("/api/supplier-rules", response_model=SupplierRuleModel, status_code=201)
async def add_supplier_rule(request: SupplierRuleRequest) -> SupplierRuleModel:
    try:
        created = deps.supplier_rule_store.add(SupplierRule(**request.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return deps.rule_model(created)


@router.patch("/api/supplier-rules/{rule_id}", response_model=SupplierRuleModel)
async def update_supplier_rule(rule_id: int, request: SupplierRuleUpdate) -> SupplierRuleModel:
    try:
        updated = deps.supplier_rule_store.update(
            rule_id, request.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail=f"No rule with id {rule_id}")
    return deps.rule_model(updated)


@router.delete("/api/supplier-rules/{rule_id}", status_code=204, response_class=Response)
async def delete_supplier_rule(rule_id: int) -> Response:
    deps.supplier_rule_store.delete(rule_id)
    return Response(status_code=204)


@router.get("/api/master-data/tables/{table_key}/export.csv", response_class=Response)
async def export_master_data(table_key: str) -> Response:
    """The whole table as CSV, which is what a spreadsheet already speaks."""
    try:
        table = deps.master_data_store.table(table_key)
        content = rows_to_csv(deps.master_data_store, table_key)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{table.key}.csv"'},
    )


@router.post("/api/master-data/tables/{table_key}/import", response_model=MasterDataImport)
async def import_master_data(table_key: str, file: UploadFile = File(...)) -> MasterDataImport:
    """Add every row the file holds that the table can take.

    A row that cannot be stored is skipped and reported rather than failing the
    file, so importing a register that partly overlaps an existing one adds the
    part that is new.
    """
    content = await file.read(deps.MAX_FILE_SIZE + 1)
    if len(content) > deps.MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="The file exceeds the 20 MB limit")
    try:
        text = decode_spreadsheet(content)
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=415,
            detail="That file is neither UTF-8 nor Windows-1252 text, so its rows cannot be read.",
        ) from exc
    try:
        report = csv_to_rows(deps.master_data_store, table_key, text)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MasterDataImport(added=report.added, skipped=report.skipped, reasons=report.reasons)


@router.get("/api/master-data/tables/{table_key}/rows", response_model=list[dict[str, Any]])
async def list_master_data_rows(
    table_key: str,
    query: str = "",
    sort: str = "",
    descending: bool = False,
    filter: Annotated[list[str], Query()] = [],
) -> list[dict[str, Any]]:
    """Rows, narrowed by a search over everything and by column.

    Each `filter` is `column:value`; the column name cannot contain a colon,
    so splitting once leaves any colon in the value alone.
    """
    filters: dict[str, str] = {}
    for item in filter:
        column, separator, value = item.partition(":")
        if separator:
            filters[column] = value
    try:
        return deps.master_data_store.rows(
            table_key, query=query, sort=sort, descending=descending, filters=filters
        )
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/master-data/tables/{table_key}/rows", response_model=dict[str, Any], status_code=201)
async def add_master_data_row(table_key: str, request: MasterDataRowRequest) -> dict[str, Any]:
    try:
        return deps.master_data_store.add(table_key, request.values)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateRow as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/master-data/tables/{table_key}/rows/from-datasets", response_model=list[dict[str, Any]])
async def seed_master_data_rows(table_key: str) -> list[dict[str, Any]]:
    """Fill a table from the labelled documents, adding only what is missing."""
    try:
        table = deps.master_data_store.table(table_key)
    except UnknownTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not table.seed_entity:
        raise HTTPException(
            status_code=400,
            detail=f"{table.label} is not built from a labelled field.",
        )

    values: list[str] = []
    for dataset in deps.dataset_store.list_datasets():
        for document in deps.dataset_store.list_documents(dataset.name):
            label_file = deps.dataset_store.read_labels(dataset.name, document.name)
            if label_file is None:
                continue
            value = label_file.labels.get(table.seed_entity)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    return deps.master_data_store.seed(table_key, values)


@router.patch("/api/master-data/tables/{table_key}/rows/{identifier}", response_model=dict[str, Any])
async def update_master_data_row(
    table_key: str,
    identifier: str,
    request: MasterDataRowRequest,
) -> dict[str, Any]:
    try:
        return deps.master_data_store.update(table_key, identifier, request.values)
    except (UnknownTable, UnknownRow) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateRow as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/api/master-data/tables/{table_key}/rows/{identifier}",
    status_code=204,
    response_class=Response,
)
async def delete_master_data_row(table_key: str, identifier: str) -> Response:
    try:
        deps.master_data_store.delete(table_key, identifier)
    except (UnknownTable, UnknownRow) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)
