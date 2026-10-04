"""Every store opens the shared database the same way."""

import sqlite3

import pytest

from app.evaluation.store import EvaluationStore
from app.services import db
from app.services.master_data import MasterDataStore
from app.services.run_store import RunStore

# Write-ahead logging, PRAGMA and file locking are SQLite's own.
pytestmark = pytest.mark.sqlite_only
from app.services.supplier_rules import SupplierRuleStore


def journal_mode(path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()


def test_each_store_leaves_the_database_in_write_ahead_mode(tmp_path) -> None:
    """Under the rollback journal a Lab write locked the UI's reads out."""
    for index, store in enumerate((RunStore, EvaluationStore, MasterDataStore, SupplierRuleStore)):
        path = tmp_path / f"{index}.db"
        store(path)
        assert journal_mode(path) == "wal"


def test_a_reader_is_not_locked_out_by_an_open_write(tmp_path) -> None:
    path = tmp_path / "docuflow.db"
    db.prepare(path)
    with db.connect(path) as setup:
        setup.execute("CREATE TABLE t (x INTEGER)")

    writer = sqlite3.connect(path)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t VALUES (1)")
    try:
        with db.connect(path) as reader:
            assert reader.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
    finally:
        writer.rollback()
        writer.close()


def test_a_missing_column_is_added_and_an_existing_one_left_alone(tmp_path) -> None:
    path = tmp_path / "docuflow.db"
    with db.connect(path) as connection:
        connection.execute("CREATE TABLE t (a TEXT)")
        db.add_missing_columns(connection, "t", {"a": "INTEGER", "b": "TEXT DEFAULT 'x'"})
        columns = {row[1]: row[2] for row in connection.execute("PRAGMA table_info(t)")}

    assert columns == {"a": "TEXT", "b": "TEXT"}


def test_a_legacy_run_that_recorded_no_model_is_not_attributed_to_lm_studio(tmp_path) -> None:
    """The provider backfill named LM Studio for every model it did not host."""
    path = tmp_path / "docuflow.db"
    store = EvaluationStore(path)
    from app.domain.models import PromptConfiguration

    evaluation_id = store.start(
        dataset="d", model="Not used", prompts=PromptConfiguration(), total_documents=1
    )
    with db.connect(path) as connection:
        connection.execute("UPDATE evaluations SET provider = NULL WHERE id = ?", (evaluation_id,))

    reopened = EvaluationStore(path)

    assert reopened.get_evaluation(evaluation_id).provider == "none"
