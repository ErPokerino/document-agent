"""Where a run's model happened, recorded on the run.

Past runs can be filtered by where the model ran, and that cannot be worked
out afterwards from the model id: a local model can be uninstalled, and a
hosted one renamed. It is a fact about what happened, so it is stored with
the pipeline, the page limit and everything else the run was started with.
"""

import sqlite3

from app.domain.models import PromptConfiguration
from app.evaluation.store import EvaluationStore


def make_store(tmp_path) -> EvaluationStore:
    return EvaluationStore(tmp_path / "runs.db")


def test_a_local_run_records_that_it_ran_locally(tmp_path) -> None:
    store = make_store(tmp_path)
    run = store.start(
        dataset="d",
        model="qwen/qwen3.6-35b-a3b",
        prompts=PromptConfiguration(),
        total_documents=1,
        provider="lm_studio",
    )
    assert store.get_evaluation(run).provider == "lm_studio"


def test_a_hosted_run_records_the_api_it_used(tmp_path) -> None:
    store = make_store(tmp_path)
    run = store.start(
        dataset="d",
        model="gemini-3.7-flash",
        prompts=PromptConfiguration(),
        total_documents=1,
        provider="gemini",
    )
    assert store.get_evaluation(run).provider == "gemini"


def test_a_pipeline_that_called_no_model_records_none(tmp_path) -> None:
    store = make_store(tmp_path)
    run = store.start(
        dataset="d",
        model="Not used",
        prompts=PromptConfiguration(),
        total_documents=1,
        provider="none",
    )
    assert store.get_evaluation(run).provider == "none"


def test_runs_from_before_this_column_are_placed_by_their_model(tmp_path) -> None:
    """The registry of hosted models is the best evidence available in hindsight."""
    path = tmp_path / "runs.db"
    store = make_store(tmp_path)
    local = store.start(
        dataset="d", model="qwen/qwen3.8-27b", prompts=PromptConfiguration(), total_documents=1
    )
    hosted = store.start(
        dataset="d", model="gemini-3.5-flash-lite", prompts=PromptConfiguration(), total_documents=1
    )
    # Undo the column, as a database written by the previous version would be.
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE evaluations SET provider = NULL")

    reopened = EvaluationStore(path)
    assert reopened.get_evaluation(local).provider == "lm_studio"
    assert reopened.get_evaluation(hosted).provider == "gemini"


def test_an_unspecified_run_is_local_because_that_is_the_default_provider(tmp_path) -> None:
    store = make_store(tmp_path)
    run = store.start(
        dataset="d", model="something-local", prompts=PromptConfiguration(), total_documents=1
    )
    assert store.get_evaluation(run).provider == "lm_studio"
