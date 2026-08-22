import pytest
from fastapi.testclient import TestClient

from app import main
from app.domain.models import AppSettings, ModelInfo
from app.pipeline.definition import PipelineDefinition
from app.pipeline.store import PipelineStore
from app.services.settings_store import SettingsStore


READY_MODEL = ModelInfo(id="vision-model", name="Vision Model", loaded=True)
DEFAULT_NAME = PipelineDefinition.default().name


class FakeClient:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        return [READY_MODEL]

    async def list_vision_models(self, excluded_model_ids=None):
        return [READY_MODEL]


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(model="vision-model"))
    monkeypatch.setattr(main, "settings_store", settings)
    pipelines = PipelineStore(tmp_path / "pipelines")
    # The app writes the starting point out at startup; so does this.
    pipelines.seed_default()
    monkeypatch.setattr(main, "pipeline_store", pipelines)
    monkeypatch.setattr(main, "LMStudioClient", FakeClient)
    with TestClient(main.app) as client:
        yield client


def body(name: str = "ocr-then-llm", **overrides) -> dict:
    payload = {
        "name": name,
        "description": "",
        "page_limit": 10,
        "steps": [{"kind": "render_pages", "config": {}}, {"kind": "llm_extract", "config": {}}],
    }
    payload.update(overrides)
    return payload


def test_the_default_pipeline_is_there_from_the_start(api) -> None:
    listed = api.get("/api/pipelines").json()

    assert [pipeline["name"] for pipeline in listed] == [DEFAULT_NAME]
    assert listed[0]["problems"] == []


def test_the_step_catalogue_describes_what_each_step_needs(api) -> None:
    catalogue = api.get("/api/pipelines/steps").json()

    extraction = next(step for step in catalogue if step["kind"] == "llm_extract")
    assert extraction["produces"] == ["entities"]
    assert extraction["requires_any"] == ["images", "text"]
    assert extraction["label"]


def test_a_pipeline_can_be_saved_and_read_back(api) -> None:
    assert api.put("/api/pipelines/ocr-then-llm", json=body()).status_code == 200

    assert api.get("/api/pipelines/ocr-then-llm").json()["steps"][0]["kind"] == "render_pages"
    assert {p["name"] for p in api.get("/api/pipelines").json()} == {DEFAULT_NAME, "ocr-then-llm"}


def test_saving_under_a_different_name_than_the_body_is_refused(api) -> None:
    response = api.put("/api/pipelines/one", json=body("another"))

    assert response.status_code == 400


def test_a_pipeline_that_could_not_run_is_refused_when_saved(api) -> None:
    broken = body("broken", steps=[{"kind": "llm_extract", "config": {}}])

    response = api.put("/api/pipelines/broken", json=broken)

    assert response.status_code == 400
    assert "images or text" in response.json()["detail"]


def test_a_rule_that_is_not_a_regex_is_refused_when_saved(api) -> None:
    payload = body(
        "bad-rule",
        steps=[
            {"kind": "render_pages", "config": {}},
            {"kind": "llm_extract", "config": {}},
            {"kind": "regex_refine", "config": {"rules": [{"entity": "date", "pattern": "([x"}]}},
        ]
    )

    response = api.put("/api/pipelines/bad-rule", json=payload)

    assert response.status_code == 400


def test_a_pipeline_can_be_deleted(api) -> None:
    api.put("/api/pipelines/ocr-then-llm", json=body())

    assert api.delete("/api/pipelines/ocr-then-llm").status_code == 204
    assert api.get("/api/pipelines/ocr-then-llm").status_code == 404


def test_the_pipeline_in_use_cannot_be_deleted(api) -> None:
    api.put("/api/pipelines/ocr-then-llm", json=body())
    settings = api.get("/api/settings").json()
    settings["pipeline"] = "ocr-then-llm"
    assert api.put("/api/settings", json=settings).status_code == 200

    response = api.delete("/api/pipelines/ocr-then-llm")

    assert response.status_code == 409
    assert "in use" in response.json()["detail"].lower()


def test_selecting_a_pipeline_that_does_not_exist_is_refused(api) -> None:
    settings = api.get("/api/settings").json()
    settings["pipeline"] = "never-saved"

    response = api.put("/api/settings", json=settings)

    assert response.status_code == 400


def test_a_pipeline_being_edited_can_be_checked_without_saving_it(api) -> None:
    response = api.post(
        "/api/pipelines/check", json=body(steps=[{"kind": "regex_refine", "config": {}}])
    )

    assert response.status_code == 200
    assert response.json()["problems"]
    assert api.get("/api/pipelines/ocr-then-llm").status_code == 404


def test_the_selected_pipeline_is_what_actually_runs(api, monkeypatch, tmp_path) -> None:
    """The regex step only shows up in the answer if the wiring is real."""
    import pymupdf

    from app.domain.models import FieldExtraction
    from app.pipeline import steps as step_module
    from app.services.run_store import RunStore

    class FakeExtraction:
        def __init__(self, base_url: str) -> None:
            pass

        async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages):
            return {"document_number": FieldExtraction(value="FE02 - 28569", confidence="high")}

    monkeypatch.setattr(step_module, "LMStudioClient", FakeExtraction)
    monkeypatch.setattr(main, "run_store", RunStore(tmp_path / "docuflow.db"))
    main.model_runtime_states["vision-model"] = "ready"

    api.put(
        "/api/pipelines/tidy",
        json=body(
            "tidy",
            steps=[
                {"kind": "render_pages", "config": {}},
                {"kind": "llm_extract", "config": {}},
                {
                    "kind": "regex_refine",
                    "config": {
                        "rules": [{"entity": "document_number", "pattern": r"\s*-\s*", "replacement": "-"}]
                    },
                },
            ],
        ),
    )
    settings = api.get("/api/settings").json()
    settings["pipeline"] = "tidy"
    assert api.put("/api/settings", json=settings).status_code == 200

    document = pymupdf.open()
    document.new_page()
    content = document.tobytes()
    document.close()

    response = api.post(
        "/api/documents/extract", files={"file": ("a.pdf", content, "application/pdf")}
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["document_number"]["value"] == "FE02-28569"
    assert main.run_store.get_run(response.json()["run_id"]).pipeline == "tidy"


def test_a_pipeline_can_be_renamed(api) -> None:
    api.put("/api/pipelines/ocr-then-llm", json=body())

    response = api.patch("/api/pipelines/ocr-then-llm", json={"name": "layout first"})

    assert response.status_code == 200
    assert response.json()["name"] == "layout first"
    assert api.get("/api/pipelines/ocr-then-llm").status_code == 404


def test_renaming_the_pipeline_in_use_keeps_it_in_use(api) -> None:
    api.put("/api/pipelines/ocr-then-llm", json=body())
    settings = api.get("/api/settings").json()
    settings["pipeline"] = "ocr-then-llm"
    api.put("/api/settings", json=settings)

    api.patch("/api/pipelines/ocr-then-llm", json={"name": "layout first"})

    assert api.get("/api/settings").json()["pipeline"] == "layout first"


def test_renaming_onto_an_existing_name_is_refused(api) -> None:
    api.put("/api/pipelines/ocr-then-llm", json=body())

    response = api.patch("/api/pipelines/ocr-then-llm", json={"name": DEFAULT_NAME})

    assert response.status_code == 400
    assert api.get("/api/pipelines/ocr-then-llm").status_code == 200


def test_the_page_limit_belongs_to_the_pipeline(api) -> None:
    response = api.put("/api/pipelines/short", json=body("short", page_limit=2))

    assert response.status_code == 200
    assert api.get("/api/pipelines/short").json()["page_limit"] == 2
