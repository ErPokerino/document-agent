import pytest

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction, PromptConfiguration
from app.evaluation.scoring import score_document
from app.evaluation.store import EvaluationStore


ENTITIES = [
    EntityDefinition(name="currency", format=EntityFormat.currency, description="x"),
    EntityDefinition(name="total_amount", format=EntityFormat.decimal, description="x"),
]


@pytest.fixture
def store(tmp_path) -> EvaluationStore:
    return EvaluationStore(tmp_path / "docuflow.db")


def start(store: EvaluationStore, total: int = 2) -> int:
    return store.start(
        dataset="invoices",
        model="vision-model",
        prompts=PromptConfiguration(),
        total_documents=total,
    )


def outcomes(currency: str | None, total: float | None, confidence: str = "high"):
    return score_document(
        ENTITIES,
        {"currency": "EUR", "total_amount": 125.31},
        {
            "currency": FieldExtraction(value=currency, confidence=confidence),
            "total_amount": FieldExtraction(value=total, confidence=confidence),
        },
    )


def test_a_started_evaluation_is_running(store) -> None:
    evaluation_id = start(store)

    detail = store.get_evaluation(evaluation_id)
    assert detail.status == "running"
    assert detail.total_documents == 2
    assert detail.completed_documents == 0


def test_progress_advances_as_documents_complete(store) -> None:
    evaluation_id = start(store)

    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1000)

    assert store.get_evaluation(evaluation_id).completed_documents == 1


def test_metrics_are_computed_from_the_recorded_items(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1000)
    store.record_document(evaluation_id, "b.pdf", outcomes("USD", 125.31), elapsed_ms=1000)
    store.finish(evaluation_id, "completed")

    metrics = store.get_evaluation(evaluation_id).metrics

    assert metrics.total == 4
    assert metrics.matched == 3
    assert metrics.per_entity["currency"].accuracy == 0.5
    assert metrics.per_entity["total_amount"].accuracy == 1.0


def test_confidence_calibration_is_available(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("USD", 125.31, confidence="high"), elapsed_ms=1)
    store.finish(evaluation_id, "completed")

    assert store.get_evaluation(evaluation_id).metrics.per_confidence["high"].accuracy == 0.5


def test_a_document_that_failed_is_recorded_without_stopping_the_run(store) -> None:
    evaluation_id = start(store)

    store.record_document_failure(evaluation_id, "broken.pdf", "The file is not a valid PDF")
    store.finish(evaluation_id, "completed")

    detail = store.get_evaluation(evaluation_id)
    assert detail.completed_documents == 1
    assert detail.failures == [("broken.pdf", "The file is not a valid PDF")]


def test_finishing_stores_the_final_status_and_time(store) -> None:
    evaluation_id = start(store)

    store.finish(evaluation_id, "cancelled")

    detail = store.get_evaluation(evaluation_id)
    assert detail.status == "cancelled"
    assert detail.finished_at is not None


def test_a_failed_evaluation_keeps_its_error(store) -> None:
    evaluation_id = start(store)

    store.finish(evaluation_id, "failed", error="LM Studio is not reachable")

    assert store.get_evaluation(evaluation_id).error == "LM Studio is not reachable"


def test_evaluations_are_listed_newest_first(store) -> None:
    first = start(store)
    second = start(store)

    assert [evaluation.id for evaluation in store.list_evaluations()] == [second, first]


def test_the_prompts_are_snapshotted_so_a_later_edit_does_not_rewrite_history(store) -> None:
    prompts = PromptConfiguration()
    prompts.system_prompt = "The prompt as it was when this ran"
    evaluation_id = store.start(
        dataset="invoices", model="vision-model", prompts=prompts, total_documents=1
    )

    assert store.get_evaluation(evaluation_id).prompts.system_prompt == "The prompt as it was when this ran"


def test_per_document_results_can_be_inspected(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("USD", 125.31), elapsed_ms=1500)

    documents = store.get_evaluation(evaluation_id).documents

    assert documents[0].name == "a.pdf"
    assert documents[0].elapsed_ms == 1500
    assert {item.entity: item.matched for item in documents[0].items} == {
        "currency": False,
        "total_amount": True,
    }


def test_an_unknown_evaluation_has_no_detail(store) -> None:
    assert store.get_evaluation(999) is None


def test_a_stale_running_evaluation_is_marked_interrupted(store) -> None:
    evaluation_id = start(store)

    # The backend restarted while a run was in flight; nothing is driving it now.
    EvaluationStore(store.path).mark_interrupted()

    assert store.get_evaluation(evaluation_id).status == "failed"


def test_the_page_limit_of_the_run_is_remembered(store) -> None:
    evaluation_id = store.start(
        dataset="invoices",
        model="vision-model",
        prompts=PromptConfiguration(),
        total_documents=1,
        max_pages=3,
    )

    assert store.get_evaluation(evaluation_id).max_pages == 3


def test_timing_is_reported_in_total_and_on_average(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1000)
    store.record_document(evaluation_id, "b.pdf", outcomes("EUR", 125.31), elapsed_ms=3000)

    detail = store.get_evaluation(evaluation_id)
    assert detail.total_elapsed_ms == 4000
    assert detail.average_elapsed_ms == 2000


def test_a_failed_document_does_not_skew_the_average(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=2000)
    store.record_document_failure(evaluation_id, "b.pdf", "boom")

    detail = store.get_evaluation(evaluation_id)
    assert detail.total_elapsed_ms == 2000
    assert detail.average_elapsed_ms == 2000


def test_an_evaluation_with_no_timings_reports_none(store) -> None:
    detail = store.get_evaluation(start(store))

    assert detail.total_elapsed_ms == 0
    assert detail.average_elapsed_ms is None


def test_an_evaluation_can_be_deleted_with_its_results(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1000)

    assert store.delete(evaluation_id) is True
    assert store.get_evaluation(evaluation_id) is None
    assert store.list_evaluations() == []


def test_deleting_an_unknown_evaluation_reports_it(store) -> None:
    assert store.delete(999) is False


def test_a_run_where_everything_worked_is_completed(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1)
    store.record_document(evaluation_id, "b.pdf", outcomes("EUR", 125.31), elapsed_ms=1)

    store.complete(evaluation_id)

    detail = store.get_evaluation(evaluation_id)
    assert detail.status == "completed"
    assert detail.succeeded_documents == 2
    assert detail.failed_documents == 0
    assert detail.pending_documents == 0


def test_a_run_with_some_failures_is_partial_not_completed(store) -> None:
    # Reporting "completed, 85%" for a run where six of ten documents never
    # reached the model is the headline number lying.
    evaluation_id = start(store, total=3)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1)
    store.record_document_failure(evaluation_id, "b.pdf", "Model is unloaded")

    store.complete(evaluation_id)

    detail = store.get_evaluation(evaluation_id)
    assert detail.status == "partial"
    assert detail.succeeded_documents == 1
    assert detail.failed_documents == 1
    assert detail.pending_documents == 1


def test_a_run_where_every_document_failed_is_failed(store) -> None:
    evaluation_id = start(store, total=2)
    store.record_document_failure(evaluation_id, "a.pdf", "boom")
    store.record_document_failure(evaluation_id, "b.pdf", "boom")

    store.complete(evaluation_id)

    assert store.get_evaluation(evaluation_id).status == "failed"


def test_a_run_that_scored_nothing_at_all_is_failed(store) -> None:
    evaluation_id = start(store, total=2)

    store.complete(evaluation_id)

    assert store.get_evaluation(evaluation_id).status == "failed"


def test_the_outcome_of_each_attempted_document_is_available(store) -> None:
    evaluation_id = start(store, total=3)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1)
    store.record_document_failure(evaluation_id, "b.pdf", "boom")

    assert store.attempted_documents(evaluation_id) == {"a.pdf": "ok", "b.pdf": "failed"}


def test_reopening_a_run_puts_it_back_to_running(store) -> None:
    evaluation_id = start(store)
    store.record_document_failure(evaluation_id, "a.pdf", "boom")
    store.complete(evaluation_id)

    store.reopen(evaluation_id)

    detail = store.get_evaluation(evaluation_id)
    assert detail.status == "running"
    assert detail.finished_at is None
    assert detail.error is None


def test_a_retried_document_replaces_its_failure(store) -> None:
    evaluation_id = start(store, total=1)
    store.record_document_failure(evaluation_id, "a.pdf", "Model is unloaded")
    store.complete(evaluation_id)

    store.reopen(evaluation_id)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=2000)
    store.complete(evaluation_id)

    detail = store.get_evaluation(evaluation_id)
    assert detail.status == "completed"
    assert detail.failed_documents == 0
    assert detail.succeeded_documents == 1
    assert detail.metrics.accuracy == 1.0
    assert detail.failures == []


def test_a_run_stored_as_completed_before_partial_existed_is_reclassified(store, tmp_path) -> None:
    evaluation_id = start(store, total=3)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1)
    store.record_document_failure(evaluation_id, "b.pdf", "Model is unloaded")
    store.finish(evaluation_id, "completed")  # what the old code wrote

    EvaluationStore(tmp_path / "docuflow.db")  # reopening runs the migration

    assert store.get_evaluation(evaluation_id).status == "partial"


def test_reclassifying_leaves_genuinely_complete_runs_alone(store, tmp_path) -> None:
    evaluation_id = start(store, total=1)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1)
    store.finish(evaluation_id, "completed")

    EvaluationStore(tmp_path / "docuflow.db")

    assert store.get_evaluation(evaluation_id).status == "completed"


def test_reclassifying_does_not_resurrect_a_cancelled_run(store, tmp_path) -> None:
    evaluation_id = start(store, total=3)
    store.finish(evaluation_id, "cancelled")

    EvaluationStore(tmp_path / "docuflow.db")

    assert store.get_evaluation(evaluation_id).status == "cancelled"


def test_token_usage_is_recorded_per_document(store) -> None:
    evaluation_id = start(store)

    store.record_document(
        evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1000,
        prompt_tokens=1500, completion_tokens=90,
    )

    document = store.get_evaluation(evaluation_id).documents[0]
    assert document.prompt_tokens == 1500
    assert document.completion_tokens == 90


def test_token_usage_is_summed_over_the_run(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1, prompt_tokens=1000, completion_tokens=50)
    store.record_document(evaluation_id, "b.pdf", outcomes("EUR", 125.31), elapsed_ms=1, prompt_tokens=1200, completion_tokens=70)

    detail = store.get_evaluation(evaluation_id)
    assert detail.prompt_tokens == 2200
    assert detail.completion_tokens == 120


def test_a_run_without_token_counts_reports_zero(store) -> None:
    evaluation_id = start(store)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1)

    detail = store.get_evaluation(evaluation_id)
    assert detail.prompt_tokens == 0
    assert detail.completion_tokens == 0
    assert detail.documents[0].prompt_tokens is None


def test_a_retried_document_replaces_its_token_counts(store) -> None:
    evaluation_id = start(store, total=1)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1, prompt_tokens=999, completion_tokens=9)

    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 125.31), elapsed_ms=1, prompt_tokens=100, completion_tokens=5)

    detail = store.get_evaluation(evaluation_id)
    assert detail.prompt_tokens == 100
    assert detail.completion_tokens == 5


def test_a_run_remembers_the_pipeline_it_was_started_with(store) -> None:
    evaluation_id = store.start(
        dataset="invoices",
        model="vision-model",
        prompts=PromptConfiguration(),
        total_documents=1,
        pipeline="ocr-then-llm",
    )

    assert store.get_evaluation(evaluation_id).pipeline == "ocr-then-llm"


def test_a_run_from_before_pipelines_existed_reads_as_the_default(tmp_path) -> None:
    import sqlite3

    from app.pipeline.definition import PipelineDefinition

    path = tmp_path / "docuflow.db"
    evaluation_id = start(EvaluationStore(path))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE evaluations SET pipeline = NULL WHERE id = ?", (evaluation_id,))

    assert EvaluationStore(path).get_evaluation(evaluation_id).pipeline == PipelineDefinition.default().name


def test_pages_sent_to_document_ai_are_recorded_and_totalled(store) -> None:
    evaluation_id = start(store, total=2)

    store.record_document(
        evaluation_id, "a.pdf", outcomes("EUR", 1.0), 100, ocr_pages=2, layout_pages=2
    )
    store.record_document(
        evaluation_id, "b.pdf", outcomes("EUR", 1.0), 100, ocr_pages=3, layout_pages=0
    )

    detail = store.get_evaluation(evaluation_id)
    assert detail.ocr_pages == 5
    assert detail.layout_pages == 2
    assert detail.documents[0].ocr_pages == 2


def test_a_run_that_never_touched_document_ai_counts_no_pages(store) -> None:
    evaluation_id = start(store, total=1)
    store.record_document(evaluation_id, "a.pdf", outcomes("EUR", 1.0), 100)

    assert store.get_evaluation(evaluation_id).ocr_pages == 0


def test_a_run_records_the_steps_that_actually_ran(store) -> None:
    """A pipeline name is a label: it can be edited, and two pipelines can be
    renamed into each other's names. What ran is the list of steps."""
    evaluation_id = store.start(
        dataset="invoices",
        model="m",
        prompts=PromptConfiguration(),
        total_documents=1,
        pipeline="Layout then LLM",
        steps=["document_ai_layout", "llm_extract"],
    )

    assert store.get_evaluation(evaluation_id).steps == ["document_ai_layout", "llm_extract"]


def test_a_run_from_before_the_steps_were_recorded_says_nothing_rather_than_guessing(store) -> None:
    evaluation_id = start(store)

    assert store.get_evaluation(evaluation_id).steps == []
