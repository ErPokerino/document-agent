import csv
import io

from app.domain.models import PromptConfiguration
from app.evaluation.export import evaluation_to_csv
from app.evaluation.store import (
    EvaluationDetail,
    EvaluationDocument,
    EvaluationItem,
)
from app.evaluation.scoring import EvaluationMetrics


def detail(documents) -> EvaluationDetail:
    return EvaluationDetail(
        id=7,
        created_at="2026-08-20T19:24:00+00:00",
        finished_at="2026-08-20T20:14:00+00:00",
        dataset="Test-Dataset",
        model="qwen/qwen3.8-27b",
        status="completed",
        total_documents=len(documents),
        completed_documents=len(documents),
        error=None,
        max_pages=1,
        succeeded_documents=sum(d.status == "ok" for d in documents),
        failed_documents=sum(d.status == "failed" for d in documents),
        pending_documents=0,
        total_elapsed_ms=1000,
        average_elapsed_ms=1000,
        prompt_tokens=0,
        completion_tokens=0,
        metrics=EvaluationMetrics(),
        prompts=PromptConfiguration(),
        documents=documents,
    )


def rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def test_one_row_per_entity_of_each_document() -> None:
    document = EvaluationDocument(
        name="invoice.pdf",
        status="ok",
        error=None,
        elapsed_ms=2500,
        items=[
            EvaluationItem(entity="currency", expected="EUR", actual="EUR", confidence="high", matched=True),
            EvaluationItem(entity="date", expected="2026-06-23", actual="2026-03-06", confidence="high", matched=False),
        ],
    )

    parsed = rows(evaluation_to_csv(detail([document])))

    assert [row["entity"] for row in parsed] == ["currency", "date"]
    assert parsed[0]["matched"] == "true"
    assert parsed[1]["matched"] == "false"
    assert parsed[1]["expected"] == "2026-06-23"
    assert parsed[1]["actual"] == "2026-03-06"


def test_every_row_carries_the_run_context() -> None:
    document = EvaluationDocument(
        name="invoice.pdf", status="ok", error=None, elapsed_ms=2500,
        items=[EvaluationItem(entity="currency", expected="EUR", actual="EUR", confidence="high", matched=True)],
    )

    row = rows(evaluation_to_csv(detail([document])))[0]

    assert row["run_id"] == "7"
    assert row["dataset"] == "Test-Dataset"
    assert row["model"] == "qwen/qwen3.8-27b"
    assert row["max_pages"] == "1"
    assert row["document"] == "invoice.pdf"
    assert row["elapsed_ms"] == "2500"


def test_a_failed_document_is_still_a_row_carrying_its_error() -> None:
    document = EvaluationDocument(
        name="broken.pdf", status="failed", error="Model is unloaded", elapsed_ms=None, items=[]
    )

    parsed = rows(evaluation_to_csv(detail([document])))

    assert len(parsed) == 1
    assert parsed[0]["document"] == "broken.pdf"
    assert parsed[0]["document_status"] == "failed"
    assert parsed[0]["error"] == "Model is unloaded"
    assert parsed[0]["entity"] == ""


def test_a_null_value_is_written_as_an_empty_cell() -> None:
    document = EvaluationDocument(
        name="invoice.pdf", status="ok", error=None, elapsed_ms=1,
        items=[EvaluationItem(entity="supplier_name", expected=None, actual=None, confidence="low", matched=True)],
    )

    row = rows(evaluation_to_csv(detail([document])))[0]

    assert row["expected"] == ""
    assert row["actual"] == ""


def test_numbers_keep_their_own_formatting() -> None:
    document = EvaluationDocument(
        name="invoice.pdf", status="ok", error=None, elapsed_ms=1,
        items=[EvaluationItem(entity="total_amount", expected=125.31, actual=125.4, confidence="high", matched=False)],
    )

    row = rows(evaluation_to_csv(detail([document])))[0]

    assert row["expected"] == "125.31"
    assert row["actual"] == "125.4"


def test_a_value_containing_a_separator_survives_the_round_trip() -> None:
    document = EvaluationDocument(
        name="invoice.pdf", status="ok", error=None, elapsed_ms=1,
        items=[EvaluationItem(entity="supplier_name", expected='ACME, "the" Ltd', actual="ACME", confidence="high", matched=False)],
    )

    row = rows(evaluation_to_csv(detail([document])))[0]

    assert row["expected"] == 'ACME, "the" Ltd'


def test_a_run_with_no_documents_still_has_a_header() -> None:
    text = evaluation_to_csv(detail([]))

    assert text.splitlines()[0].startswith("run_id,")
    assert rows(text) == []


def test_token_usage_is_exported_per_document() -> None:
    document = EvaluationDocument(
        name="invoice.pdf", status="ok", error=None, elapsed_ms=2500,
        prompt_tokens=1500, completion_tokens=90,
        items=[EvaluationItem(entity="currency", expected="EUR", actual="EUR", confidence="high", matched=True)],
    )

    row = rows(evaluation_to_csv(detail([document])))[0]

    assert row["prompt_tokens"] == "1500"
    assert row["completion_tokens"] == "90"
