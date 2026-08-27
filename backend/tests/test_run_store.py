import pytest

from app.domain.models import FieldExtraction, ModelExecutionProfile, PromptConfiguration
from app.services.run_store import RunStore


def extraction() -> dict[str, FieldExtraction]:
    return {
        "date": FieldExtraction(value="2026-07-31", confidence="high"),
        "total_amount": FieldExtraction(value=125.31, confidence="medium"),
        "currency": FieldExtraction(value=None, confidence="low"),
    }


@pytest.fixture
def store(tmp_path) -> RunStore:
    return RunStore(tmp_path / "docuflow.db")


def record(store: RunStore, filename: str = "invoice21.pdf", **overrides) -> int:
    payload = {
        "filename": filename,
        "content": b"%PDF-1.4 fake",
        "model": "vision-model",
        "prompts": PromptConfiguration(),
        "extraction": extraction(),
        "page_count": 3,
        "processed_pages": 1,
        "elapsed_ms": 4200,
        "source": "workspace",
    }
    payload.update(overrides)
    return store.record_run(**payload)


def test_a_recorded_run_can_be_read_back(store) -> None:
    run_id = record(store)

    run = store.get_run(run_id)
    assert run.filename == "invoice21.pdf"
    assert run.model == "vision-model"
    assert run.elapsed_ms == 4200
    assert run.extraction["date"].value == "2026-07-31"
    assert run.extraction["currency"].value is None


def test_runs_are_listed_newest_first(store) -> None:
    first = record(store, "a.pdf")
    second = record(store, "b.pdf")

    assert [run.id for run in store.list_runs()] == [second, first]


def test_the_prompt_configuration_is_snapshotted_with_the_run(store) -> None:
    prompts = PromptConfiguration()
    prompts.system_prompt = "A prompt that will be changed later"
    run_id = record(store, prompts=prompts)

    assert store.get_run(run_id).prompts.system_prompt == "A prompt that will be changed later"


def test_the_same_file_is_recognized_across_runs(store) -> None:
    first = record(store, "invoice.pdf", content=b"identical")
    second = record(store, "renamed.pdf", content=b"identical")

    runs = {run.id: run for run in store.list_runs()}
    assert runs[first].file_sha256 == runs[second].file_sha256


def test_a_run_without_corrections_is_not_validated(store) -> None:
    run_id = record(store)

    assert store.get_run(run_id).has_corrections is False


def test_corrections_are_stored_against_the_run(store) -> None:
    run_id = record(store)

    store.record_corrections(run_id, {"total_amount": 999.0})

    run = store.get_run(run_id)
    assert run.corrections == {"total_amount": 999.0}
    assert run.has_corrections is True


def test_correcting_the_same_field_twice_keeps_the_last_value(store) -> None:
    run_id = record(store)

    store.record_corrections(run_id, {"total_amount": 999.0})
    store.record_corrections(run_id, {"total_amount": 111.0})

    assert store.get_run(run_id).corrections == {"total_amount": 111.0}


def test_a_correction_to_null_is_kept(store) -> None:
    run_id = record(store)

    store.record_corrections(run_id, {"currency": None})

    assert store.get_run(run_id).corrections == {"currency": None}


def test_validated_values_merge_corrections_over_the_extraction(store) -> None:
    run_id = record(store)
    store.record_corrections(run_id, {"total_amount": 999.0})

    # This is what gets promoted to ground truth: what a human signed off on.
    assert store.validated_values(run_id) == {
        "date": "2026-07-31",
        "total_amount": 999.0,
        "currency": None,
    }


def test_an_unknown_run_has_no_detail(store) -> None:
    assert store.get_run(4242) is None


def test_corrections_for_an_unknown_run_are_rejected(store) -> None:
    with pytest.raises(ValueError, match="4242"):
        store.record_corrections(4242, {"total_amount": 1.0})


def test_the_database_survives_being_reopened(store, tmp_path) -> None:
    run_id = record(store)

    reopened = RunStore(tmp_path / "docuflow.db")
    assert reopened.get_run(run_id).filename == "invoice21.pdf"


def test_only_runs_a_human_validated_are_offered_as_ground_truth(store) -> None:
    record(store, "untouched.pdf")
    validated = record(store, "reviewed.pdf")
    store.record_corrections(validated, {"total_amount": 999.0})

    assert [run.filename for run in store.list_runs(validated_only=True)] == ["reviewed.pdf"]


def test_the_original_pdf_is_kept_so_a_run_can_become_ground_truth(store) -> None:
    run_id = record(store, content=b"%PDF-1.4 the real bytes")

    run = store.get_run(run_id)
    assert store.read_document(run.file_sha256) == b"%PDF-1.4 the real bytes"


def test_the_same_pdf_is_stored_once(store, tmp_path) -> None:
    record(store, "a.pdf", content=b"identical")
    record(store, "b.pdf", content=b"identical")

    stored = list((tmp_path / "documents").glob("*.pdf"))
    assert len(stored) == 1


def test_an_unknown_document_hash_reads_as_missing(store) -> None:
    assert store.read_document("0" * 64) is None


def test_a_run_records_the_pipeline_that_produced_it(store) -> None:
    run_id = record(store, pipeline="ocr-then-llm")

    assert store.get_run(run_id).pipeline == "ocr-then-llm"


def test_a_run_recorded_before_pipelines_existed_reads_as_the_default(tmp_path) -> None:
    import sqlite3

    from app.pipeline.definition import PipelineDefinition

    path = tmp_path / "docuflow.db"
    store = RunStore(path)
    run_id = record(store)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE runs SET pipeline = NULL WHERE id = ?", (run_id,))

    assert RunStore(path).get_run(run_id).pipeline == PipelineDefinition.default().name


def test_a_run_records_the_steps_that_actually_ran(store) -> None:
    run_id = record(store, steps=["document_ai_layout", "llm_extract"])

    assert store.get_run(run_id).steps == ["document_ai_layout", "llm_extract"]


def test_a_run_from_before_the_steps_were_recorded_lists_none(store) -> None:
    assert store.get_run(record(store)).steps == []


def test_the_model_execution_profile_is_snapshotted_with_the_run(store) -> None:
    """A model id alone cannot explain accuracy changes after runtime settings change."""
    profile = ModelExecutionProfile(
        provider="lm_studio",
        profile="standard",
        context_length=8192,
        parallel=1,
        eval_batch_size=512,
        flash_attention=True,
        offload_kv_cache_to_gpu=False,
        temperature=0,
        seed=0,
        reasoning_effort="none",
    )

    run_id = record(store, execution_profile=profile)

    assert store.get_run(run_id).execution_profile == profile
    assert store.list_runs()[0].execution_profile == profile
