"""Models trained on labelled datasets: storing them, serving them, and not cheating with them."""

import asyncio
import io
import json
import time
import zipfile

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.domain.models import AppSettings, EntityDefinition, KnnParameters, PromptConfiguration
from app.evaluation.datasets import DatasetStore
from app.evaluation.store import EvaluationStore
from app.main import app
from app.pipeline.compiler import PipelineError, build_steps
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind, describe_problems, filled_entities
from app.pipeline.engine import PipelineContext
from app.services.settings_store import SettingsStore
from app.training.artifacts import ArtifactStore, InvalidArtifact
from app.training.knn import KnnModel, TrainingDocument

SUPPLIER = EntityDefinition(name="supplier_class", format="category", description="Who sent it.", source="derived")
TEXTS = {
    "acme-1.pdf": ("ACME S.r.l. Fattura numero 101 via Roma Milano partita IVA 0123", "ACME"),
    "acme-2.pdf": ("ACME S.r.l. Fattura numero 102 via Roma Milano partita IVA 0123", "ACME"),
    "globex-1.pdf": ("Globex Corporation Invoice 77 Springfield total amount due", "Globex"),
    "globex-2.pdf": ("Globex Corporation Invoice 78 Springfield total amount due", "Globex"),
}


def pdf(text: str) -> bytes:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def trained(store: ArtifactStore, k: int = 1):
    documents = [TrainingDocument("train", name, name, {"supplier_class": label}) for name, (_, label) in TEXTS.items()]
    model = KnnModel.train([text for text, _ in TEXTS.values()], documents, KnnParameters(k=k))
    manifest = {
        "kind": "knn_tfidf", "name": "suppliers", "created_at": "2026-10-03T00:00:00+00:00",
        "entities": ["supplier_class"], "parameters": KnnParameters(k=k).model_dump(mode="json"),
        "training": {"datasets": ["train"], "reader": [{"kind": "read_pdf_text", "processor_id": None, "only_without_pdf_text": False}],
                     "documents": [{"dataset": "train", "document": d.document, "sha256": d.sha256} for d in documents]},
    }
    return store.save(manifest, model.files())


# -- the model ---------------------------------------------------------------------


def test_a_document_takes_the_class_of_its_nearest_labelled_neighbour(tmp_path) -> None:
    model = ArtifactStore(tmp_path).load(trained(ArtifactStore(tmp_path)).id)

    prediction = model.predict("Globex Corporation Invoice 99 Springfield", "supplier_class")

    assert prediction.value == "Globex"
    assert prediction.nearest.document.startswith("globex")
    assert 0 < prediction.score <= 1


def test_leave_one_out_never_lets_a_document_find_itself(tmp_path) -> None:
    """A copy of one file under another name is left out with it."""
    documents = [
        TrainingDocument("a", "x.pdf", "same", {"t": "A"}),
        TrainingDocument("b", "x-copy.pdf", "same", {"t": "A"}),
        TrainingDocument("a", "y.pdf", "other", {"t": "B"}),
    ]
    model = KnnModel.train(["identical text here", "identical text here", "different words entirely"], documents, KnnParameters())

    outcomes = model.leave_one_out("t")

    assert [prediction.nearest.sha256 for _, prediction in outcomes[:2]] == ["other", "other"]


def test_a_document_never_labelled_for_a_field_does_not_vote_on_it(tmp_path) -> None:
    documents = [TrainingDocument("a", "1.pdf", "1", {}), TrainingDocument("a", "2.pdf", "2", {"t": "B"})]
    model = KnnModel.train(["alpha beta gamma", "zeta eta theta"], documents, KnnParameters())

    assert model.predict("alpha beta gamma", "t").value == "B"


def test_neighbours_vote_by_similarity(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    model = store.load(trained(store, k=3).id)

    prediction = model.predict("ACME S.r.l. Fattura numero 103 via Roma", "supplier_class")

    assert prediction.value == "ACME"
    assert prediction.agreement > 0.5


# -- the registry ------------------------------------------------------------------


def test_the_same_model_trained_twice_is_one_artefact(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    assert trained(store).id == trained(store).id
    assert len(store.list()) == 1


def test_an_artefact_travels_as_a_zip_and_keeps_its_id(tmp_path) -> None:
    source = ArtifactStore(tmp_path / "here")
    stored = trained(source)

    arrived = ArtifactStore(tmp_path / "there").import_archive(source.export(stored.id))

    assert arrived.id == stored.id
    assert arrived.manifest["imported"] is True


def test_an_archive_carrying_anything_but_the_declared_files_is_refused(tmp_path) -> None:
    """A pickle among them would run its own code when loaded."""
    source = ArtifactStore(tmp_path / "here")
    exported = source.export(trained(source).id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(exported)) as original, zipfile.ZipFile(buffer, "w") as tampered:
        for name in original.namelist():
            tampered.writestr(name, original.read(name))
        tampered.writestr("model.pkl", b"\x80\x04")

    with pytest.raises(InvalidArtifact, match="model.pkl"):
        ArtifactStore(tmp_path / "there").import_archive(buffer.getvalue())


def test_a_model_whose_files_changed_is_not_loaded(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    stored = trained(store)
    path = tmp_path / stored.id / "documents.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[0]["labels"]["supplier_class"] = "Globex"
    path.write_text(json.dumps(entries), encoding="utf-8")

    with pytest.raises(InvalidArtifact, match="no longer match"):
        ArtifactStore(tmp_path).load(stored.id)


# -- the pipeline step -------------------------------------------------------------


def predictor_pipeline(artifact: str, threshold: float = 0.0) -> PipelineDefinition:
    return PipelineDefinition(
        name="Knn",
        steps=[
            PipelineStep(kind=StepKind.read_pdf_text),
            PipelineStep(kind=StepKind.artifact_predict, config={"artifact_id": artifact, "entities": ["supplier_class"], "minimum_similarity": threshold}),
        ],
    )


def test_a_trained_model_needs_text_read_before_it() -> None:
    definition = PipelineDefinition(name="x", steps=[PipelineStep(kind=StepKind.artifact_predict, config={})])

    assert any("needs text" in problem for problem in describe_problems(definition))


def test_the_fields_a_model_fills_count_as_filled() -> None:
    assert filled_entities(predictor_pipeline("a" * 32)) == {"supplier_class"}


def test_a_pipeline_naming_a_model_that_is_gone_does_not_compile(tmp_path) -> None:
    with pytest.raises(PipelineError, match="No trained model"):
        build_steps(predictor_pipeline("a" * 32), prompts=PromptConfiguration(), entities=[SUPPLIER], artifacts=ArtifactStore(tmp_path))


def test_a_model_cannot_fill_a_field_it_never_learned(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    definition = predictor_pipeline(trained(store).id)
    definition.steps[1].config["entities"] = ["currency"]

    with pytest.raises(PipelineError, match="not trained on: currency"):
        build_steps(definition, prompts=PromptConfiguration(), entities=[SUPPLIER], artifacts=store)


def run(definition, store, text: str):
    steps = build_steps(definition, prompts=PromptConfiguration(), entities=[SUPPLIER], artifacts=store)
    context = PipelineContext(filename="new.pdf", content=pdf(text), model="m", lm_studio_url="")

    async def go():
        for step in steps:
            await step.run(context)
        return context

    return asyncio.run(go()).artifacts["extraction"]["supplier_class"]


def test_the_step_fills_the_field_and_says_what_it_rests_on(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    field = run(predictor_pipeline(trained(store).id), store, "Globex Corporation Invoice 99 Springfield")

    assert field.value == "Globex"
    assert field.score is not None
    assert "train/globex" in field.evidence


def test_below_the_threshold_the_step_answers_nothing_and_says_why(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    field = run(predictor_pipeline(trained(store).id, threshold=0.99), store, "Globex Corporation Invoice 99 Springfield")

    assert field.value is None
    assert "below the 0.99" in field.warning


# -- the API -----------------------------------------------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(prompts=PromptConfiguration(entities=[*PromptConfiguration().entities, SUPPLIER])))
    monkeypatch.setattr(deps, "settings_store", settings)
    monkeypatch.setattr(deps, "dataset_store", DatasetStore(tmp_path / "datasets"))
    monkeypatch.setattr(deps, "evaluation_store", EvaluationStore(tmp_path / "docuflow.db"))
    deps.release_model_operation()
    with TestClient(app) as client:
        yield client
    deps.release_model_operation()


def seed(api, dataset: str, names) -> None:
    api.post("/api/datasets", json={"name": dataset})
    for name in names:
        text, label = TEXTS[name]
        api.post(f"/api/datasets/{dataset}/documents", files={"file": (name, pdf(text), "application/pdf")})
        api.put(f"/api/datasets/{dataset}/documents/{name}/labels", json={"labels": {"supplier_class": label}})


def reading_pipeline() -> None:
    deps.pipeline_store.save(PipelineDefinition(
        name="Local text",
        steps=[PipelineStep(kind=StepKind.read_pdf_text), PipelineStep(kind=StepKind.llm_extract)],
    ))


def wait_for(api, job_id: int) -> dict:
    for _ in range(200):
        job = next(job for job in api.get("/api/training/jobs").json() if job["id"] == job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("The training job did not finish")


def test_training_reads_the_datasets_and_registers_a_validated_model(api) -> None:
    seed(api, "train", TEXTS)
    reading_pipeline()

    started = api.post("/api/training/models", json={
        "name": "suppliers", "datasets": ["train"], "pipeline": "Local text", "entities": ["supplier_class"],
    })
    assert started.status_code == 202
    job = wait_for(api, started.json()["id"])

    assert job["status"] == "completed", job
    [model] = api.get("/api/artifacts").json()
    assert model["id"] == job["artifact_id"]
    assert model["documents"] == 4
    assert model["reader"] == ["read_pdf_text"]
    assert model["validation"]["supplier_class"]["accuracy"] == 1.0


def test_a_temporal_cutoff_learns_only_from_earlier_documents(api) -> None:
    seed(api, "train", TEXTS)
    dated = {"acme-1.pdf": "2025-01-10", "acme-2.pdf": "2026-05-01", "globex-1.pdf": "2025-03-02", "globex-2.pdf": "2026-07-09"}
    for name, day in dated.items():
        api.put(f"/api/datasets/train/documents/{name}/labels", json={"labels": {"supplier_class": TEXTS[name][1], "date": day}})
    reading_pipeline()

    job = wait_for(api, api.post("/api/training/models", json={
        "name": "before 2026", "datasets": ["train"], "pipeline": "Local text", "entities": ["supplier_class"],
        "cutoff_entity": "date", "cutoff_before": "2026-01-01",
    }).json()["id"])

    [model] = api.get("/api/artifacts").json()
    assert job["status"] == "completed"
    assert model["documents"] == 2
    assert model["excluded_by_cutoff"] == 2


def test_the_lab_refuses_to_score_a_model_on_the_documents_it_learned_from(api) -> None:
    seed(api, "train", TEXTS)
    reading_pipeline()
    job = wait_for(api, api.post("/api/training/models", json={
        "name": "suppliers", "datasets": ["train"], "pipeline": "Local text", "entities": ["supplier_class"],
    }).json()["id"])
    deps.pipeline_store.save(predictor_pipeline(job["artifact_id"]))
    settings = deps.settings_store.read()
    settings.pipeline = "Knn"
    deps.settings_store.write(settings)

    response = api.post("/api/evaluations", json={"dataset": "train"})

    assert response.status_code == 409
    assert "4 of the 4 documents in 'train' were used to train 'suppliers'" in response.json()["detail"]


def test_a_model_in_use_by_a_pipeline_cannot_be_deleted(api) -> None:
    stored = trained(deps.artifact_store)
    deps.pipeline_store.save(predictor_pipeline(stored.id))

    response = api.delete(f"/api/artifacts/{stored.id}")

    assert response.status_code == 409
    assert "Knn" in response.json()["detail"]


def test_a_pipeline_reading_text_another_way_is_warned_about(api) -> None:
    stored = trained(deps.artifact_store)
    definition = predictor_pipeline(stored.id)
    definition.steps[0] = PipelineStep(kind=StepKind.document_ai_ocr, config={"processor_id": "p", "project_id": "x", "location": "eu"})

    warnings = deps.saved_pipeline(definition).warnings

    assert any("learned from text read by read_pdf_text" in warning for warning in warnings)


def test_remote_training_targets_are_listed_as_not_connected(api) -> None:
    providers = api.get("/api/training/providers").json()

    assert {provider["id"] for provider in providers} >= {"vertex_gemini_sft", "document_ai_custom"}
    assert all(provider["status"] == "not_connected" for provider in providers)


# -- fine-tuning examples ------------------------------------------------------------


def test_an_example_is_worded_as_gemini_is_asked_at_run_time() -> None:
    """A tuned model learns the question it was trained on."""
    from app.services.gemini import GeminiClient
    from app.training.sft import example

    prompts = PromptConfiguration()
    labels = {entity.name: "x" for entity in prompts.entities}

    line = example("vertex_gemini", prompts, labels, "ACME invoice", total_pages=2, processed_pages=2)

    assert line["systemInstruction"]["parts"][0]["text"] == GeminiClient._system_prompt(prompts)
    assert "ACME invoice" in line["contents"][0]["parts"][0]["text"]
    answer = json.loads(line["contents"][1]["parts"][0]["text"])
    assert answer["confidence"]["currency"] == "high"


def test_a_document_missing_a_label_the_model_is_asked_for_is_not_an_example() -> None:
    """Writing null in its place would teach the model to answer nothing."""
    from app.training.sft import example

    with pytest.raises(ValueError, match="not labelled for"):
        example("openai_chat", PromptConfiguration(), {"currency": "EUR"}, "text", total_pages=1, processed_pages=1)


def test_an_export_writes_one_example_per_fully_labelled_document(api) -> None:
    seed(api, "train", ["acme-1.pdf", "globex-1.pdf"])
    complete = {entity.name: None for entity in PromptConfiguration().entities}
    api.put("/api/datasets/train/documents/acme-1.pdf/labels", json={"labels": {**complete, "currency": "EUR"}})
    reading_pipeline()

    job = wait_for(api, api.post("/api/training/exports", json={
        "name": "invoices", "datasets": ["train"], "pipeline": "Local text", "format": "openai_chat",
    }).json()["id"])

    assert job["status"] == "completed", job
    assert job["examples"] == 1
    assert any("globex-1.pdf: not labelled for" in line for line in job["skipped"])
    exported = api.get(f"/api/training/exports/{job['output']}")
    [line] = exported.text.strip().splitlines()
    assert json.loads(line)["messages"][2]["role"] == "assistant"


# -- many algorithms -----------------------------------------------------------------


def test_every_algorithm_says_whether_it_can_train_here(api) -> None:
    listed = {entry["id"]: entry for entry in api.get("/api/training/algorithms").json()}

    assert listed["logistic_regression"]["status"] == "available"
    assert listed["jev"]["status"] == "not_connected"
    assert {"knn_tfidf", "lightgbm", "xgboost", "catboost", "tabpfn"} <= set(listed)
    assert all(spec["name"] and spec["label"] for entry in listed.values() for spec in entry["parameters"])


@pytest.mark.parametrize("algorithm", ["logistic_regression", "lightgbm", "xgboost", "catboost"])
def test_a_classifier_is_trained_validated_stored_and_served_as_a_step(api, algorithm) -> None:
    seed(api, "train", TEXTS)
    reading_pipeline()

    job = wait_for(api, api.post("/api/training/models", json={
        "name": algorithm, "algorithm": algorithm, "datasets": ["train"], "pipeline": "Local text",
        "entities": ["supplier_class"], "text": {"reduce_to": 3},
    }).json()["id"])

    assert job["status"] == "completed", job
    model = next(entry for entry in api.get("/api/artifacts").json() if entry["id"] == job["artifact_id"])
    assert model["kind"] == "classifier" and model["algorithm"] == algorithm
    assert model["validation_method"].endswith("grouped by file")
    field = run(predictor_pipeline(job["artifact_id"]), deps.artifact_store, TEXTS["globex-1.pdf"][0])
    assert field.value in ("ACME", "Globex")
    assert "probability" in field.evidence


def test_a_classifier_travels_as_a_zip_with_only_declared_files(api, tmp_path) -> None:
    seed(api, "train", TEXTS)
    reading_pipeline()
    job = wait_for(api, api.post("/api/training/models", json={
        "name": "lr", "algorithm": "logistic_regression", "datasets": ["train"], "pipeline": "Local text", "entities": ["supplier_class"],
    }).json()["id"])

    exported = deps.artifact_store.export(job["artifact_id"])
    arrived = ArtifactStore(tmp_path / "elsewhere").import_archive(exported)

    assert arrived.id == job["artifact_id"]
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        assert all(name.endswith((".json", ".npy")) for name in archive.namelist())


def test_extracted_fields_can_be_features_beside_the_text(api) -> None:
    seed(api, "train", TEXTS)
    for name, (_, label) in TEXTS.items():
        api.put(f"/api/datasets/train/documents/{name}/labels", json={"labels": {"supplier_class": label, "currency": "EUR" if label == "ACME" else "USD"}})
    reading_pipeline()

    job = wait_for(api, api.post("/api/training/models", json={
        "name": "with currency", "algorithm": "lightgbm", "datasets": ["train"], "pipeline": "Local text",
        "entities": ["supplier_class"], "input_fields": ["currency"], "text": {"reduce_to": 2},
    }).json()["id"])

    assert job["status"] == "completed", job
    [model] = [entry for entry in api.get("/api/artifacts").json() if entry["id"] == job["artifact_id"]]
    assert model["input_fields"] == ["currency"]


def test_unknown_parameters_and_unavailable_algorithms_are_refused(api) -> None:
    seed(api, "train", TEXTS)
    reading_pipeline()
    base = {"name": "x", "datasets": ["train"], "pipeline": "Local text", "entities": ["supplier_class"]}

    assert "no parameter named depth" in api.post("/api/training/models", json={**base, "algorithm": "logistic_regression", "parameters": {"depth": 3}}).json()["detail"]
    assert "not connected" in api.post("/api/training/models", json={**base, "algorithm": "jev"}).json()["detail"]
    assert "reads the text alone" in api.post("/api/training/models", json={**base, "algorithm": "knn_tfidf", "input_fields": ["currency"]}).json()["detail"]


def test_folds_keep_every_copy_of_a_file_together() -> None:
    from app.training.corpus import LabelledDocument, ReadDocument
    from app.training.trainer import folds_for

    items = [ReadDocument(LabelledDocument("d", f"{i}.pdf", sha, b"", {}), "t") for i, sha in enumerate(["a", "b", "a", "c", "d", "e", "f"])]

    folds = folds_for(items)

    assert len(folds) == 5
    assert any({0, 2} <= set(fold) for fold in folds)
