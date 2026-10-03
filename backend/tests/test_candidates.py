"""Several methods propose a value; a strategy chooses; the Lab measures each method."""

import asyncio

from fastapi.testclient import TestClient

from app.api import deps
from app.domain.models import EntityDefinition, FieldCandidate, FieldExtraction, PromptConfiguration
from app.evaluation.methods import method_report, resimulate
from app.evaluation.scoring import score_document
from app.evaluation.store import EvaluationStore
from app.main import app
from app.pipeline.compiler import build_steps
from app.pipeline.definition import PipelineDefinition, PipelineStep, StepKind
from app.pipeline.engine import DocumentPipeline, PipelineContext, method_names
from app.pipeline.resolution import FieldRule, ResolutionConfig, resolve

CURRENCY = EntityDefinition(name="currency", format="currency", description="Currency.")


class Writes:
    """A step that writes fixed values, as a method would."""

    def __init__(self, kind: str, values: dict, confidence: str = "medium", score: float | None = None) -> None:
        self.kind = kind
        self.values = values
        self.confidence = confidence
        self.score = score

    async def run(self, context: PipelineContext) -> None:
        extraction = dict(context.artifacts.get("extraction") or {})
        for name, value in self.values.items():
            extraction[name] = FieldExtraction(value=value, confidence=self.confidence, score=self.score)
        context.artifacts["extraction"] = extraction


class Untouched:
    kind = "regex_refine"

    async def run(self, context: PipelineContext) -> None:
        context.artifacts["extraction"] = dict(context.artifacts["extraction"])


def run(steps) -> dict:
    context = PipelineContext(filename="a.pdf", content=b"", model="m", lm_studio_url="")
    return asyncio.run(DocumentPipeline(steps).run(context)).artifacts["extraction"]


def candidate(method: str, value, confidence: str = "medium", score: float | None = None) -> FieldCandidate:
    return FieldCandidate(method=method, value=value, confidence=confidence, score=score)


# -- recording -----------------------------------------------------------------------


def test_every_step_that_writes_a_field_leaves_a_candidate() -> None:
    field = run([Writes("llm_extract", {"currency": "EUR"}), Writes("artifact_predict", {"currency": "USD"})])["currency"]

    assert [(c.method, c.value) for c in field.candidates] == [("llm_extract", "EUR"), ("artifact_predict", "USD")]
    assert field.value == "USD"


def test_a_step_that_leaves_a_field_alone_proposes_nothing_for_it() -> None:
    field = run([Writes("llm_extract", {"currency": "EUR"}), Untouched()])["currency"]

    assert [c.method for c in field.candidates] == ["llm_extract"]


def test_a_second_method_agreeing_is_recorded_not_merged() -> None:
    """Agreement between independent methods is evidence; comparing values would hide it."""
    field = run([Writes("llm_extract", {"currency": "EUR"}), Writes("artifact_predict", {"currency": "EUR"})])["currency"]

    assert len(field.candidates) == 2


def test_a_kind_repeated_in_one_pipeline_is_two_methods() -> None:
    assert method_names([Writes("regex_refine", {}), Writes("llm_extract", {}), Writes("regex_refine", {})]) == [
        "regex_refine #1", "llm_extract", "regex_refine #2",
    ]


# -- resolving -----------------------------------------------------------------------


def test_last_is_what_step_order_always_meant() -> None:
    chosen = resolve(CURRENCY, [candidate("llm_extract", "EUR"), candidate("regex_refine", "USD")], FieldRule())

    assert chosen.value == "USD"


def test_priority_takes_the_first_listed_method_that_answered() -> None:
    candidates = [candidate("llm_extract", "EUR"), candidate("trained: x", None), candidate("regex_refine", "USD")]

    chosen = resolve(CURRENCY, candidates, FieldRule(strategy="priority", priority=["trained: x", "llm_extract"]))

    assert chosen.value == "EUR"
    assert "llm_extract" in chosen.evidence


def test_priority_passes_over_a_score_below_the_minimum() -> None:
    candidates = [candidate("trained: x", "USD", score=0.4), candidate("llm_extract", "EUR")]

    chosen = resolve(CURRENCY, candidates, FieldRule(strategy="priority", priority=["trained: x", "llm_extract"], minimum_score=0.6))

    assert chosen.value == "EUR"


def test_best_confidence_prefers_the_surer_method() -> None:
    chosen = resolve(CURRENCY, [candidate("a", "EUR", "high"), candidate("b", "USD", "low")], FieldRule(strategy="best_confidence"))

    assert chosen.value == "EUR"


def test_agreement_takes_the_majority_and_is_sure_of_a_unanimous_one() -> None:
    majority = resolve(CURRENCY, [candidate("a", "EUR"), candidate("b", "eur"), candidate("c", "USD")], FieldRule(strategy="agreement"))
    unanimous = resolve(CURRENCY, [candidate("a", "EUR", "low"), candidate("b", "EUR", "medium")], FieldRule(strategy="agreement"))

    assert majority.value == "EUR"
    assert unanimous.confidence == "high"


def test_agreement_abstains_when_the_methods_split_evenly() -> None:
    """A tie broken by step order would be the old rule wearing a new name."""
    chosen = resolve(CURRENCY, [candidate("a", "EUR"), candidate("b", "USD")], FieldRule(strategy="agreement"))

    assert chosen.value is None
    assert "disagree" in chosen.warning


def test_a_resolve_step_in_a_pipeline_chooses_and_proposes_nothing() -> None:
    definition = PipelineDefinition(
        name="x",
        steps=[
            PipelineStep(kind=StepKind.read_pdf_text),
            PipelineStep(kind=StepKind.llm_extract),
            PipelineStep(kind=StepKind.resolve_candidates, config={"default": {"strategy": "priority", "priority": ["llm_extract"]}}),
        ],
    )
    [*_, resolver] = build_steps(definition, prompts=PromptConfiguration(entities=[CURRENCY]), entities=[CURRENCY])

    field = run([Writes("llm_extract", {"currency": "EUR"}), Writes("regex_refine", {"currency": "USD"}), resolver])["currency"]

    assert field.value == "EUR"
    assert [c.method for c in field.candidates] == ["llm_extract", "regex_refine"]


# -- the Lab -------------------------------------------------------------------------


def stored_run(tmp_path, monkeypatch) -> int:
    store = EvaluationStore(tmp_path / "docuflow.db")
    monkeypatch.setattr(deps, "evaluation_store", store)
    prompts = PromptConfiguration(entities=[CURRENCY])
    evaluation_id = store.start(dataset="d", model="m", prompts=prompts, total_documents=2)
    answers = {
        # The model is right on the first, the trained model on the second;
        # the pipeline kept the trained model's answer both times.
        "1.pdf": ("EUR", [candidate("llm_extract", "EUR"), candidate("trained: x", "USD")]),
        "2.pdf": ("GBP", [candidate("llm_extract", "EUR"), candidate("trained: x", "GBP")]),
    }
    for name, (expected, candidates) in answers.items():
        field = FieldExtraction(value=candidates[-1].value, confidence="medium", candidates=candidates)
        store.record_document(evaluation_id, name, score_document([CURRENCY], {"currency": expected}, {"currency": field}), elapsed_ms=1)
    return evaluation_id


def test_the_lab_scores_each_method_and_the_ceiling_they_share(tmp_path, monkeypatch) -> None:
    evaluation_id = stored_run(tmp_path, monkeypatch)
    detail = deps.evaluation_store.get_evaluation(evaluation_id)

    [currency] = method_report(detail.prompts.entities, detail.documents)

    assert currency.resolved_accuracy == 0.5
    assert currency.oracle_accuracy == 1.0
    assert {name: tally.accuracy for name, tally in currency.methods.items()} == {"llm_extract": 0.5, "trained: x": 0.5}


def test_another_strategy_is_tried_on_a_stored_run_without_running_it(tmp_path, monkeypatch) -> None:
    evaluation_id = stored_run(tmp_path, monkeypatch)
    client = TestClient(app)

    trial = client.post(
        f"/api/evaluations/{evaluation_id}/resolve",
        json={"default": {"strategy": "priority", "priority": ["llm_extract"]}},
    ).json()

    assert trial["per_entity"]["currency"] == {"matched": 1, "total": 2, "accuracy": 0.5}
    detail = client.get(f"/api/evaluations/{evaluation_id}").json()
    assert detail["methods"][0]["oracle_accuracy"] == 1.0
    assert detail["documents"][0]["items"][0]["candidates"][0]["method"] == "llm_extract"


def test_a_field_without_candidates_keeps_its_score_in_a_trial(tmp_path, monkeypatch) -> None:
    store = EvaluationStore(tmp_path / "docuflow.db")
    prompts = PromptConfiguration(entities=[CURRENCY])
    evaluation_id = store.start(dataset="d", model="m", prompts=prompts, total_documents=1)
    store.record_document(evaluation_id, "1.pdf", score_document([CURRENCY], {"currency": "EUR"}, {"currency": FieldExtraction(value="EUR", confidence="high")}), elapsed_ms=1)

    trial = resimulate([CURRENCY], store.get_evaluation(evaluation_id).documents, ResolutionConfig())

    assert (trial.matched, trial.total) == (1, 1)
