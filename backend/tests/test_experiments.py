"""Experiments: a grid of pipelines and models, run as ordinary runs and compared on shared documents."""

import time
from dataclasses import dataclass, field

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import deps
from app.domain.models import MODEL_NOT_USED, AppSettings, FieldExtraction, ModelInfo
from app.evaluation.datasets import DatasetStore
from app.evaluation.experiments import ExperimentStore, ModelChoice, compare, execution_order, plan_cells
from app.evaluation.store import EvaluationStore
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
from app.services.run_store import RunStore
from app.services.settings_store import SettingsStore

VISION = PipelineDefinition(name="Vision", steps=[PipelineStep(kind=StepKind.render_pages), PipelineStep(kind=StepKind.llm_extract)])
TEXT = PipelineDefinition(name="Text", steps=[PipelineStep(kind=StepKind.read_pdf_text), PipelineStep(kind=StepKind.llm_extract)])
NO_MODEL = PipelineDefinition(
    name="No model",
    steps=[PipelineStep(kind=StepKind.read_pdf_text), PipelineStep(kind=StepKind.artifact_predict, config={"entities": ["supplier_class"]})],
)


# -- the plan ------------------------------------------------------------------------


def test_a_pipeline_that_calls_no_model_is_one_cell_whatever_models_are_chosen() -> None:
    cells = plan_cells([NO_MODEL, TEXT], [ModelChoice("lm_studio", "a"), ModelChoice("gemini", "b")])

    assert [(cell.pipeline, cell.model) for cell in cells] == [("No model", MODEL_NOT_USED), ("Text", "a"), ("Text", "b")]


def test_a_vision_pipeline_is_not_paired_with_a_model_that_cannot_read_images() -> None:
    [cell] = plan_cells([VISION], [ModelChoice("lm_studio", "text-only", vision=False)])

    assert "does not read images" in cell.skipped


def test_cells_run_grouped_by_model_so_each_local_model_loads_once() -> None:
    cells = plan_cells([VISION, TEXT], [ModelChoice("lm_studio", "b"), ModelChoice("lm_studio", "a")])

    assert [cells[index].model for index in execution_order(cells)] == ["a", "a", "b", "b"]


# -- the comparison ------------------------------------------------------------------


@dataclass
class Item:
    entity: str
    matched: bool


@dataclass
class Document:
    name: str
    status: str
    items: list
    elapsed_ms: int | None = 1000


@dataclass
class Detail:
    documents: list = field(default_factory=list)


def detail(results: dict[str, bool | None]) -> Detail:
    return Detail([
        Document(name, "failed" if right is None else "ok", [] if right is None else [Item("currency", right)])
        for name, right in results.items()
    ])


def test_cells_are_compared_only_on_the_documents_every_cell_scored() -> None:
    """A document one cell failed on would otherwise count against the other alone."""
    result = compare({0: detail({"a": True, "b": True, "c": None}), 1: detail({"a": True, "b": False, "c": True})})

    assert result.shared_documents == ["a", "b"]
    assert result.left_out == ["c"]
    assert [score.accuracy for score in result.cells] == [1.0, 0.5]


def test_a_small_difference_on_few_documents_is_not_called_a_win() -> None:
    names = [f"d{i}" for i in range(10)]
    best = detail({name: index != 0 for index, name in enumerate(names)})
    close = detail({name: index > 1 for index, name in enumerate(names)})

    result = compare({0: best, 1: close})

    assert result.cells[0].verdict == "best"
    assert result.cells[1].verdict == "indistinguishable"
    assert result.cells[1].low < result.cells[1].accuracy < result.cells[1].high


def test_a_consistent_gap_over_many_documents_is_called_worse() -> None:
    names = [f"d{i}" for i in range(60)]
    good = detail({name: True for name in names})
    poor = detail({name: index % 2 == 0 for index, name in enumerate(names)})

    assert compare({0: good, 1: poor}).cells[1].verdict == "worse"


def test_the_same_runs_always_get_the_same_interval() -> None:
    runs = {0: detail({f"d{i}": i % 3 != 0 for i in range(12)}), 1: detail({f"d{i}": i % 4 != 0 for i in range(12)})}

    assert compare(runs) == compare(runs)


# -- the API -------------------------------------------------------------------------


READY = [
    ModelInfo(id="local-a", name="A", loaded=True),
    ModelInfo(id="local-b", name="B", loaded=False, vision=False),
]


class FakeLmStudio:
    def __init__(self, base_url: str) -> None:
        pass

    async def list_models(self, excluded_model_ids=None):
        # Only one model is in memory at a time, as in LM Studio.
        current = loads[-1] if loads else "local-a"
        return [model.model_copy(update={"loaded": model.id == current}) for model in READY]

    async def load_and_warm_model(self, model, **kwargs):
        loads.append(model)
        return {"warmup_mode": "text", "profile": "standard"}

    async def extract_entities(self, model, images, prompts, page_range, total_pages, processed_pages, document_text=""):
        answers.append(model)
        return {"currency": FieldExtraction(value="EUR" if model == "local-a" else "USD", confidence="high")}


loads: list[str] = []
answers: list[str] = []


def pdf_bytes(text: str = "Invoice EUR") -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


@pytest.fixture
def api(tmp_path, monkeypatch):
    loads.clear()
    answers.clear()
    settings = SettingsStore(tmp_path / "settings.json")
    from app.domain.models import PromptConfiguration
    from test_training import SUPPLIER, trained

    settings.write(AppSettings(model="local-a", prompts=PromptConfiguration(entities=[*PromptConfiguration().entities, SUPPLIER])))
    monkeypatch.setattr(deps, "settings_store", settings)
    monkeypatch.setattr(deps, "run_store", RunStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(deps, "evaluation_store", EvaluationStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(deps, "experiment_store", ExperimentStore(tmp_path / "docuflow.db"))
    monkeypatch.setattr(deps, "dataset_store", DatasetStore(tmp_path / "datasets"))
    monkeypatch.setattr(deps, "LMStudioClient", FakeLmStudio)
    import app.pipeline.steps as steps

    monkeypatch.setattr(steps, "LMStudioClient", FakeLmStudio)
    deps.model_runtime_states.clear()
    deps.model_runtime_states["local-a"] = "ready"
    deps.release_model_operation()
    NO_MODEL.steps[1].config["artifact_id"] = trained(deps.artifact_store).id
    for definition in (TEXT, NO_MODEL):
        deps.pipeline_store.save(definition)
    with TestClient(main.app) as client:
        client.post("/api/datasets", json={"name": "invoices"})
        for name in ("a.pdf", "b.pdf"):
            client.post("/api/datasets/invoices/documents", files={"file": (name, pdf_bytes(), "application/pdf")})
            client.put(f"/api/datasets/invoices/documents/{name}/labels", json={"labels": {"currency": "EUR"}})
        yield client
    deps.model_runtime_states.clear()
    deps.release_model_operation()


def wait(api, experiment_id: int) -> dict:
    for _ in range(300):
        experiment = api.get(f"/api/experiments/{experiment_id}").json()
        if experiment["status"] != "running":
            return experiment
        time.sleep(0.02)
    raise AssertionError("The experiment did not finish")


def test_an_experiment_runs_every_cell_as_an_ordinary_run_and_compares_them(api) -> None:
    started = api.post("/api/experiments", json={
        "dataset": "invoices", "pipelines": ["Text", "No model"],
        "models": [{"provider": "lm_studio", "model": "local-a"}, {"provider": "lm_studio", "model": "local-b"}],
    })
    assert started.status_code == 202, started.text

    experiment = wait(api, started.json()["id"])

    assert experiment["status"] == "completed"
    assert [(cell["pipeline"], cell["model"], cell["status"]) for cell in experiment["cells"]] == [
        ("Text", "local-a", "completed"), ("Text", "local-b", "completed"), ("No model", MODEL_NOT_USED, "completed"),
    ]
    # local-a was ready; only local-b had to be loaded, once.
    assert loads == ["local-b"]
    comparison = experiment["comparison"]
    assert comparison["shared_documents"] == ["a.pdf", "b.pdf"]
    assert comparison["cells"][0]["cell"] == 0 and comparison["cells"][0]["verdict"] == "best"
    run_ids = [cell["run"]["id"] for cell in experiment["cells"]]
    assert all(run["experiment_id"] == experiment["id"] for run in api.get("/api/evaluations").json() if run["id"] in run_ids)


def test_an_experiment_does_not_change_the_model_selected_in_llm(api) -> None:
    experiment = wait(api, api.post("/api/experiments", json={
        "dataset": "invoices", "pipelines": ["Text"], "models": [{"provider": "lm_studio", "model": "local-b"}],
    }).json()["id"])

    assert experiment["status"] == "completed"
    assert deps.settings_store.read().model == "local-a"


def test_a_pipeline_that_calls_a_model_needs_a_model_chosen(api) -> None:
    response = api.post("/api/experiments", json={"dataset": "invoices", "pipelines": ["Text"], "models": []})

    assert response.status_code == 400
    assert "no model is chosen" in response.json()["detail"]


def test_a_model_not_installed_here_is_refused_before_anything_runs(api) -> None:
    response = api.post("/api/experiments", json={
        "dataset": "invoices", "pipelines": ["Text"], "models": [{"provider": "lm_studio", "model": "elsewhere"}],
    })

    assert response.status_code == 400
    assert deps.experiment_store.list() == []


def test_deleting_an_experiment_keeps_its_runs(api) -> None:
    experiment = wait(api, api.post("/api/experiments", json={
        "dataset": "invoices", "pipelines": ["No model"], "models": [],
    }).json()["id"])

    assert api.delete(f"/api/experiments/{experiment['id']}").status_code == 204
    assert experiment["cells"][0]["run"]["id"] in [run["id"] for run in api.get("/api/evaluations").json()]
