"""Categorical fields: closed and open vocabularies, and how they are scored."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import deps
from app.domain.models import AppSettings, EntityDefinition, FieldExtraction, PromptConfiguration
from app.evaluation.classification import NO_CLASS, classification_report
from app.evaluation.datasets import DatasetStore
from app.evaluation.scoring import FieldOutcome, score_document, values_match
from app.main import app
from app.services.custom_extractor import schema_override
from app.services.field_validation import validate_result
from app.services.field_wording import described_for_reader
from app.services.gemini import GeminiClient
from app.services.lm_studio import LMStudioClient
from app.services.settings_store import SettingsStore

CLOSED = EntityDefinition(
    name="document_type", format="category", description="What kind of document this is.",
    categories=["Invoice", "Credit note"],
)
OPEN = EntityDefinition(name="cost_centre", format="category", description="The cost centre.")


def test_two_spellings_of_one_category_are_refused() -> None:
    with pytest.raises(ValidationError):
        EntityDefinition(name="t", format="category", description="d", categories=["Invoice", " invoice"])


def test_only_a_category_lists_categories() -> None:
    with pytest.raises(ValidationError):
        EntityDefinition(name="t", format="text", description="d", categories=["A"])


def test_a_closed_category_takes_the_vocabulary_spelling() -> None:
    result = validate_result({"document_type": {"value": "credit  NOTE", "confidence": "high"}}, [CLOSED])

    assert result["document_type"].value == "Credit note"


def test_a_closed_category_refuses_a_class_nobody_defined() -> None:
    """A class outside the list would be one no reader may answer and no label may hold."""
    result = validate_result({"document_type": {"value": "Receipt", "confidence": "high"}}, [CLOSED])

    assert result["document_type"].value is None
    assert "2 categories" in result["document_type"].warning


def test_an_open_category_keeps_any_well_formed_class() -> None:
    result = validate_result({"cost_centre": {"value": "  CC 42 ", "confidence": "medium"}}, [OPEN])

    assert result["cost_centre"].value == "CC 42"


def test_a_local_model_cannot_write_a_class_outside_a_closed_vocabulary() -> None:
    schema = LMStudioClient._generation_schema([CLOSED, OPEN])

    assert schema["properties"]["document_type"]["anyOf"][0] == {"type": "string", "enum": ["Invoice", "Credit note"]}
    assert "enum" not in schema["properties"]["cost_centre"]["anyOf"][0]


def test_gemini_is_given_the_vocabulary_as_an_enum() -> None:
    schema = GeminiClient.generation_schema([CLOSED])

    assert schema["properties"]["document_type"]["enum"] == ["Invoice", "Credit note"]


def test_the_custom_extractor_derives_a_class_rather_than_quoting_one() -> None:
    """'Credit note' may be printed nowhere on a credit note."""
    entity_type = schema_override([CLOSED])["entityTypes"][0]["properties"][0]

    assert entity_type["method"] == "DERIVE"
    assert "Invoice; Credit note" in entity_type["description"]


def test_an_open_category_is_told_no_list() -> None:
    assert described_for_reader(OPEN) == "The cost centre."


def test_categories_match_whatever_the_case_and_spacing() -> None:
    assert values_match("Credit note", "credit   NOTE", CLOSED)
    assert not values_match("Credit note", "Invoice", CLOSED)


def test_a_score_a_step_computed_is_kept_with_the_outcome() -> None:
    outcomes = score_document(
        [CLOSED], {"document_type": "Invoice"},
        {"document_type": FieldExtraction(value="Invoice", confidence="high", score=0.91)},
    )

    assert outcomes[0].score == 0.91


def outcome(expected, actual, score=None, confidence="high") -> FieldOutcome:
    return FieldOutcome(
        entity="document_type", expected=expected, actual=actual, confidence=confidence,
        matched=(expected or "").casefold() == (actual or "").casefold() if actual is not None else expected is None,
        score=score,
    )


def test_a_rare_class_never_answered_pulls_the_macro_average_down() -> None:
    """Accuracy hides it: nine right out of ten while the rare class is never found."""
    outcomes = [outcome("Invoice", "Invoice") for _ in range(9)] + [outcome("Credit note", "Invoice")]

    report = classification_report("document_type", outcomes)

    assert report.accuracy == 0.9
    credit = next(score for score in report.classes if score.label == "Credit note")
    assert credit.recall == 0 and credit.f1 == 0
    assert report.macro_f1 < 0.5


def test_an_abstention_is_its_own_column_not_a_wrong_class() -> None:
    report = classification_report("document_type", [outcome("Invoice", None), outcome("Invoice", "Invoice")])

    assert report.labels == ["Invoice", NO_CLASS]
    assert report.confusion == [[1, 1], [0, 0]]
    invoice = report.classes[0]
    assert invoice.precision == 1.0 and invoice.recall == 0.5


def test_the_coverage_curve_follows_the_score_when_every_answer_has_one() -> None:
    outcomes = [
        outcome("Invoice", "Invoice", score=0.95),
        outcome("Invoice", "Credit note", score=0.60),
        outcome("Credit note", "Credit note", score=0.80),
        outcome("Invoice", None),
    ]

    report = classification_report("document_type", outcomes)

    assert report.ranked_by == "score"
    assert [(point.threshold, point.answered, point.coverage, point.accuracy) for point in report.coverage] == [
        (0.95, 1, 0.25, 1.0),
        (0.8, 2, 0.5, 1.0),
        (0.6, 3, 0.75, 2 / 3),
    ]


def test_without_scores_the_curve_falls_back_to_the_confidence_band() -> None:
    report = classification_report(
        "document_type",
        [outcome("Invoice", "Invoice", confidence="high"), outcome("Invoice", "Credit note", confidence="low")],
    )

    assert report.ranked_by == "confidence"
    assert len(report.coverage) == 2


@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = SettingsStore(tmp_path / "settings.json")
    settings.write(AppSettings(prompts=PromptConfiguration(entities=[*PromptConfiguration().entities, CLOSED, OPEN])))
    monkeypatch.setattr(deps, "settings_store", settings)
    monkeypatch.setattr(deps, "dataset_store", DatasetStore(tmp_path / "datasets"))
    return TestClient(app)


def add_document(name: str, dataset: str = "a") -> None:
    if dataset not in {summary.name for summary in deps.dataset_store.list_datasets()}:
        deps.dataset_store.create(dataset)
    deps.dataset_store.add_document(dataset, name, b"%PDF-1.4")


def test_a_closed_category_label_is_stored_as_the_vocabulary_spells_it(api) -> None:
    add_document("x.pdf")

    response = api.put("/api/datasets/a/documents/x.pdf/labels", json={"labels": {"document_type": "invoice"}})

    assert response.status_code == 200
    assert response.json()["labels"]["document_type"] == "Invoice"


def test_a_label_outside_a_closed_category_is_refused(api) -> None:
    add_document("x.pdf")

    response = api.put("/api/datasets/a/documents/x.pdf/labels", json={"labels": {"document_type": "Receipt"}})

    assert response.status_code == 400


def test_an_open_category_learns_its_classes_from_every_dataset(api) -> None:
    for dataset, name, value in (("a", "1.pdf", "CC 1"), ("a", "2.pdf", "cc  1"), ("b", "3.pdf", "CC 2")):
        add_document(name, dataset)
        api.put(f"/api/datasets/{dataset}/documents/{name}/labels", json={"labels": {"cost_centre": value}})

    assert api.get("/api/label-values/cost_centre").json() == [
        {"value": "CC 1", "documents": 2},
        {"value": "CC 2", "documents": 1},
    ]


def test_a_run_reports_each_category_as_a_classifier(api, tmp_path, monkeypatch) -> None:
    from app.evaluation.store import EvaluationStore

    store = EvaluationStore(tmp_path / "docuflow.db")
    monkeypatch.setattr(deps, "evaluation_store", store)
    prompts = deps.settings_store.read().prompts
    evaluation_id = store.start(dataset="a", model="m", prompts=prompts, total_documents=2)
    store.record_document(evaluation_id, "1.pdf", [outcome("Invoice", "Invoice", score=0.9)], elapsed_ms=1)
    store.record_document(evaluation_id, "2.pdf", [outcome("Credit note", "Invoice", score=0.4)], elapsed_ms=1)

    detail = api.get(f"/api/evaluations/{evaluation_id}").json()

    [report] = detail["classification"]
    assert report["entity"] == "document_type"
    assert report["labels"] == ["Credit note", "Invoice"]
    assert report["confusion"] == [[0, 1], [0, 1]]
    assert detail["documents"][0]["items"][0]["score"] == 0.9
