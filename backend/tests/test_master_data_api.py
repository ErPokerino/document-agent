"""The Master Data section, over HTTP."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.services.master_data import MasterDataStore
from app.services.settings_store import SettingsStore


class FakeLMStudio:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        return [ModelInfo(id="vision-model", name="Vision Model")]

    async def list_vision_models(self, excluded_model_ids=None):
        return [ModelInfo(id="vision-model", name="Vision Model")]


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="vision-model"))
    master_data = MasterDataStore(tmp_path / "master.db")
    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "master_data_store", master_data)
    monkeypatch.setattr(main, "LMStudioClient", FakeLMStudio)
    with TestClient(main.app) as client:
        yield client, master_data


ROWS = "/api/master-data/tables/suppliers/rows"


def test_the_tables_describe_themselves(api) -> None:
    client, _ = api

    tables = client.get("/api/master-data/tables").json()

    assert [table["key"] for table in tables] == ["suppliers"]
    assert tables[0]["id_column"] == "id_subject"
    assert [column["key"] for column in tables[0]["columns"]] == [
        "id_subject",
        "name",
        "source",
        "created_at",
    ]
    assert tables[0]["columns"][0]["editable"] is False


def test_a_table_nobody_defined_is_a_404(api) -> None:
    client, _ = api

    assert client.get("/api/master-data/tables/invoices/rows").status_code == 404


def test_the_table_starts_empty(api) -> None:
    client, _ = api

    assert client.get(ROWS).json() == []


def test_a_row_can_be_added_and_comes_back_normalized(api) -> None:
    client, _ = api

    created = client.post(ROWS, json={"values": {"name": "ACME S.r.l."}})

    assert created.status_code == 201
    assert created.json()["id_subject"] == "S0001"
    assert created.json()["name"] == "acme"


def test_the_same_row_twice_is_refused_with_the_one_that_has_it(api) -> None:
    client, _ = api
    client.post(ROWS, json={"values": {"name": "ACME S.r.l."}})

    clash = client.post(ROWS, json={"values": {"name": "acme srl"}})

    assert clash.status_code == 409
    assert "S0001" in clash.json()["detail"]


def test_a_row_can_be_corrected_and_removed(api) -> None:
    client, _ = api
    client.post(ROWS, json={"values": {"name": "ACME"}})

    renamed = client.patch(f"{ROWS}/S0001", json={"values": {"name": "ACME International"}})
    assert renamed.json()["name"] == "acme international"

    assert client.delete(f"{ROWS}/S0001").status_code == 204
    assert client.get(ROWS).json() == []


def test_writing_a_generated_column_is_refused(api) -> None:
    client, _ = api
    client.post(ROWS, json={"values": {"name": "ACME"}})

    refused = client.patch(f"{ROWS}/S0001", json={"values": {"id_subject": "S9999"}})

    assert refused.status_code == 400


def test_acting_on_a_row_that_is_not_there_is_a_404(api) -> None:
    client, _ = api

    assert client.patch(f"{ROWS}/S9999", json={"values": {"name": "x"}}).status_code == 404
    assert client.delete(f"{ROWS}/S9999").status_code == 404


def test_rows_can_be_searched_and_sorted(api) -> None:
    client, _ = api
    for name in ("Zeta Trasporti", "ACME S.r.l."):
        client.post(ROWS, json={"values": {"name": name}})

    assert [row["name"] for row in client.get(f"{ROWS}?query=zeta").json()] == ["zeta trasporti"]
    assert [row["name"] for row in client.get(f"{ROWS}?sort=name").json()] == ["acme", "zeta trasporti"]
    assert [row["name"] for row in client.get(f"{ROWS}?sort=name&descending=true").json()] == [
        "zeta trasporti",
        "acme",
    ]


def test_sorting_by_a_column_that_does_not_exist_is_refused(api) -> None:
    client, _ = api

    assert client.get(f"{ROWS}?sort=turnover").status_code == 400


def test_the_table_can_be_filled_from_the_labelled_documents(api, tmp_path, monkeypatch) -> None:
    from app.evaluation.datasets import DatasetStore

    client, _ = api
    datasets = DatasetStore(tmp_path / "datasets")
    datasets.create("invoices")
    monkeypatch.setattr(main, "dataset_store", datasets)
    for name, supplier in (("a.pdf", "ACME S.r.l."), ("b.pdf", "Zeta Trasporti"), ("c.pdf", "acme srl")):
        datasets.add_document("invoices", name, b"%PDF-1.4 fake", labels={"supplier_name": supplier})

    added = client.post(f"{ROWS}/from-datasets").json()

    # Three documents, two suppliers: the third normalizes onto the first.
    assert [row["name"] for row in added] == ["acme", "zeta trasporti"]
