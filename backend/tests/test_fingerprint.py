from app.domain.models import ModelExecutionProfile, PromptConfiguration
from app.evaluation.fingerprint import configuration_fingerprint, rule_record, rules_from_records
from app.pipeline.definition import PipelineDefinition
from app.services.supplier_rules import SupplierRule


def fingerprint(**overrides):
    arguments = dict(
        dataset_snapshot={"a.pdf": {"sha256": "abc", "labels": {"currency": "EUR"}}},
        prompts=PromptConfiguration(),
        pipeline=PipelineDefinition.default(),
        execution_profile=None,
        register_rows=[{"id_subject": "S1"}],
        rules=[rule_record(SupplierRule(id_subject="S1", entity="currency", kind="fixed", value="EUR"))],
    )
    arguments.update(overrides)
    return configuration_fingerprint(**arguments)


def test_the_same_configuration_has_the_same_fingerprint() -> None:
    assert fingerprint() == fingerprint()


def test_a_changed_label_changes_the_fingerprint() -> None:
    changed = fingerprint(dataset_snapshot={"a.pdf": {"sha256": "abc", "labels": {"currency": "USD"}}})
    assert changed != fingerprint()


def test_a_changed_rule_changes_the_fingerprint() -> None:
    changed = fingerprint(
        rules=[rule_record(SupplierRule(id_subject="S1", entity="currency", kind="fixed", value="USD"))]
    )
    assert changed != fingerprint()


def test_a_recorded_rule_round_trips_without_its_database_id() -> None:
    rule = SupplierRule(id=9, id_subject="S1", entity="currency", kind="fixed", value="EUR", note="kept")
    restored = rules_from_records([rule_record(rule)])[0]
    assert restored.id is None
    assert restored.value == "EUR"
    assert restored.note == "kept"


def test_a_profile_is_part_of_the_fingerprint() -> None:
    profile = ModelExecutionProfile(provider="gemini", profile="hosted", temperature=0.2)
    assert fingerprint(execution_profile=profile) != fingerprint()
