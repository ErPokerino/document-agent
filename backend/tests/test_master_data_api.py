"""The Master Data section, over HTTP."""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.services.master_data import SubjectStore
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
    subjects = SubjectStore(tmp_path / "master.db")
    monkeypatch.setattr(main, "settings_store", settings)
    monkeypatch.setattr(main, "subject_store", subjects)
    monkeypatch.setattr(main, "LMStudioClient", FakeLMStudio)
    with TestClient(main.app) as client:
        yield client, subjects


def test_the_register_starts_empty(api) -> None:
    client, _ = api

    assert client.get("/api/master-data/subjects").json() == []


def test_a_supplier_can_be_added_and_comes_back_with_its_identifier(api) -> None:
    client, _ = api

    created = client.post("/api/master-data/subjects", json={"name": "ACME S.r.l."})

    assert created.status_code == 201
    assert created.json()["id_subject"] == "S0001"
    assert created.json()["normalized_name"] == "acme"


def test_the_same_supplier_twice_is_refused_with_the_row_that_already_has_it(api) -> None:
    client, _ = api
    client.post("/api/master-data/subjects", json={"name": "ACME S.r.l."})

    clash = client.post("/api/master-data/subjects", json={"name": "acme srl"})

    assert clash.status_code == 409
    assert "S0001" in clash.json()["detail"]


def test_a_supplier_can_be_corrected_and_removed(api) -> None:
    client, _ = api
    client.post("/api/master-data/subjects", json={"name": "ACME"})

    renamed = client.patch("/api/master-data/subjects/S0001", json={"name": "ACME International"})
    assert renamed.json()["name"] == "ACME International"

    assert client.delete("/api/master-data/subjects/S0001").status_code == 204
    assert client.get("/api/master-data/subjects").json() == []


def test_acting_on_a_supplier_that_is_not_there_is_a_404(api) -> None:
    client, _ = api

    assert client.patch("/api/master-data/subjects/S9999", json={"name": "x"}).status_code == 404
    assert client.delete("/api/master-data/subjects/S9999").status_code == 404


def test_the_register_can_be_searched(api) -> None:
    client, _ = api
    client.post("/api/master-data/subjects", json={"name": "ACME S.r.l."})
    client.post("/api/master-data/subjects", json={"name": "Zeta Trasporti"})

    found = client.get("/api/master-data/subjects?query=zeta").json()

    assert [subject["name"] for subject in found] == ["Zeta Trasporti"]


def test_the_register_can_be_filled_from_the_labelled_documents(api, tmp_path, monkeypatch) -> None:
    from app.evaluation.datasets import DatasetStore

    datasets = DatasetStore(tmp_path / "datasets")
    datasets.create("invoices")
    monkeypatch.setattr(main, "dataset_store", datasets)
    for name, supplier in (("a.pdf", "ACME S.r.l."), ("b.pdf", "Zeta Trasporti"), ("c.pdf", "acme srl")):
        datasets.add_document("invoices", name, b"%PDF-1.4 fake", labels={"supplier_name": supplier})

    added = client_seed(api)

    # Three documents, two suppliers: the third normalizes onto the first.
    assert [subject["name"] for subject in added] == ["ACME S.r.l.", "Zeta Trasporti"]


def client_seed(api):
    client, _ = api
    response = client.post("/api/master-data/subjects/from-datasets", json={"entity": "supplier_name"})
    assert response.status_code == 200, response.text
    return response.json()
