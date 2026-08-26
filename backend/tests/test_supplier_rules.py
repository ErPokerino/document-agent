"""Rules that apply to one supplier's documents and nobody else's.

Layouts repeat per supplier, and so do the exceptions: this one prefixes the
number with `Ns. Rif.`, this one always bills in euro, this one writes a date
the other way round. A general prompt cannot hold all of that without getting
worse at everything else, so the corrections live next to the supplier.

Keyed on `id_subject`, never on the supplier's name: several spellings of a
supplier legitimately resolve to the same internal id, and the id is the thing
that is either right or wrong.

Deterministic rules cost nothing and run first. A prompted rule is a second
model call and is only worth making when there is one to make.
"""

import pytest

from app.domain.models import FieldExtraction
from app.services.supplier_rules import (
    SupplierRule,
    apply_deterministic_rules,
    prompted_rules,
    rules_for,
)


def rule(entity: str, kind: str, **rest) -> SupplierRule:
    return SupplierRule(id_subject="S0001", entity=entity, kind=kind, **rest)


def extraction(**values: object) -> dict[str, FieldExtraction]:
    return {
        name: FieldExtraction(value=value, confidence="medium")
        for name, value in values.items()
    }


# -- picking the rules that apply ----------------------------------------------


def test_only_the_matched_supplier_rules_apply() -> None:
    everything = [
        SupplierRule(id_subject="S0001", entity="currency", kind="fixed", value="EUR"),
        SupplierRule(id_subject="S0002", entity="currency", kind="fixed", value="USD"),
    ]
    assert [r.value for r in rules_for(everything, "S0001")] == ["EUR"]


def test_no_supplier_means_no_rules_rather_than_all_of_them() -> None:
    """A document whose supplier was not identified must not inherit someone's rules."""
    everything = [SupplierRule(id_subject="S0001", entity="currency", kind="fixed", value="EUR")]
    assert rules_for(everything, None) == []
    assert rules_for(everything, "") == []


# -- fixed values ---------------------------------------------------------------


def test_a_fixed_rule_sets_the_field() -> None:
    result, changed = apply_deterministic_rules(
        extraction(currency="usd"), [rule("currency", "fixed", value="EUR")], document_text="",
    )
    assert result["currency"].value == "EUR"
    assert changed == ["currency"]


def test_a_fixed_rule_reports_high_confidence_because_it_is_not_a_guess() -> None:
    result, _ = apply_deterministic_rules(
        extraction(currency=None), [rule("currency", "fixed", value="EUR")], document_text="",
    )
    assert result["currency"].confidence == "high"


def test_a_rule_for_a_field_that_is_not_configured_is_ignored() -> None:
    """Entities can be renamed or removed; a stale rule must not add a field back."""
    result, changed = apply_deterministic_rules(
        extraction(currency="EUR"), [rule("vat_number", "fixed", value="IT01")], document_text="",
    )
    assert "vat_number" not in result
    assert changed == []


# -- regex over what the page said ----------------------------------------------


def test_a_regex_reads_the_value_out_of_the_document_text() -> None:
    result, changed = apply_deterministic_rules(
        extraction(document_number="0599"),
        [rule("document_number", "regex", pattern=r"Ns\. Rif\.\s*(\S+)")],
        document_text="Fattura\nNs. Rif. IVOS2607-0599\nTotale 100",
    )
    assert result["document_number"].value == "IVOS2607-0599"
    assert changed == ["document_number"]


def test_a_regex_with_no_capture_group_takes_the_whole_match() -> None:
    result, _ = apply_deterministic_rules(
        extraction(document_number=None),
        [rule("document_number", "regex", pattern=r"INV-\d{4}-\d{4}")],
        document_text="Number INV-2024-0042 issued",
    )
    assert result["document_number"].value == "INV-2024-0042"


def test_a_regex_that_matches_nothing_leaves_the_value_alone() -> None:
    """A rule that does not fire is not a reason to erase what the model read."""
    result, changed = apply_deterministic_rules(
        extraction(document_number="0599"),
        [rule("document_number", "regex", pattern=r"Ns\. Rif\.\s*(\S+)")],
        document_text="nothing like it here",
    )
    assert result["document_number"].value == "0599"
    assert changed == []


def test_a_broken_pattern_is_skipped_rather_than_failing_the_document() -> None:
    result, changed = apply_deterministic_rules(
        extraction(document_number="0599"),
        [rule("document_number", "regex", pattern=r"(unclosed")],
        document_text="anything",
    )
    assert result["document_number"].value == "0599"
    assert changed == []


def test_a_regex_falls_back_to_the_current_value_with_no_document_text() -> None:
    """A vision pipeline has no OCR text; the rule can still clean what was read."""
    result, _ = apply_deterministic_rules(
        extraction(document_number="Ns. Rif. IVOS2607"),
        [rule("document_number", "regex", pattern=r"Ns\. Rif\.\s*(\S+)")],
        document_text="",
    )
    assert result["document_number"].value == "IVOS2607"


# -- rules that need the model --------------------------------------------------


def test_a_prompted_rule_is_not_applied_here() -> None:
    """Deterministic first, and free. The model call is a separate decision."""
    original = extraction(supplier_name="ACME")
    result, changed = apply_deterministic_rules(
        original, [rule("supplier_name", "prompt", prompt="Take the name from the stamp.")],
        document_text="whatever",
    )
    assert result["supplier_name"].value == "ACME"
    assert changed == []


def test_the_prompted_rules_are_reported_so_a_call_is_only_made_when_needed() -> None:
    mixed = [
        rule("currency", "fixed", value="EUR"),
        rule("supplier_name", "prompt", prompt="Take the name from the stamp."),
        rule("date", "prompt", prompt="The date is the one beside the stamp."),
    ]
    asked = prompted_rules(mixed)
    assert [r.entity for r in asked] == ["supplier_name", "date"]


def test_no_prompted_rule_means_no_second_model_call() -> None:
    assert prompted_rules([rule("currency", "fixed", value="EUR")]) == []


# -- order and independence ------------------------------------------------------


def test_rules_do_not_disturb_the_fields_they_do_not_name() -> None:
    before = extraction(currency="usd", supplier_name="ACME", total_amount=100.0)
    result, _ = apply_deterministic_rules(
        before, [rule("currency", "fixed", value="EUR")], document_text="",
    )
    assert result["supplier_name"].value == "ACME"
    assert result["total_amount"].value == 100.0


def test_the_original_extraction_is_not_modified_in_place() -> None:
    before = extraction(currency="usd")
    apply_deterministic_rules(before, [rule("currency", "fixed", value="EUR")], document_text="")
    assert before["currency"].value == "usd"


def test_two_rules_for_one_field_apply_in_order() -> None:
    result, changed = apply_deterministic_rules(
        extraction(document_number="x"),
        [
            rule("document_number", "regex", pattern=r"Rif\.\s*(\S+)"),
            rule("document_number", "fixed", value="OVERRIDDEN"),
        ],
        document_text="Rif. ABC-1",
    )
    assert result["document_number"].value == "OVERRIDDEN"
    assert changed == ["document_number"]


def test_a_rule_kind_nobody_recognises_is_ignored() -> None:
    result, changed = apply_deterministic_rules(
        extraction(currency="EUR"), [rule("currency", "sorcery", value="???")], document_text="",
    )
    assert result["currency"].value == "EUR"
    assert changed == []


# -- storage and the API --------------------------------------------------------


def test_rules_survive_a_restart_and_keep_their_order(tmp_path) -> None:
    from app.services.supplier_rules import SupplierRuleStore

    store = SupplierRuleStore(tmp_path / "rules.db")
    store.add(SupplierRule(id_subject="S0001", entity="currency", kind="fixed", value="EUR"))
    store.add(SupplierRule(id_subject="S0001", entity="date", kind="prompt", prompt="Beside the stamp."))
    store.add(SupplierRule(id_subject="S0002", entity="currency", kind="fixed", value="USD"))

    reopened = SupplierRuleStore(tmp_path / "rules.db")
    mine = reopened.for_supplier("S0001")
    assert [rule.entity for rule in mine] == ["currency", "date"]
    assert reopened.for_supplier("S0002")[0].value == "USD"


def test_a_rule_kind_the_store_does_not_know_is_refused(tmp_path) -> None:
    from app.services.supplier_rules import SupplierRuleStore

    store = SupplierRuleStore(tmp_path / "rules.db")
    with pytest.raises(ValueError):
        store.add(SupplierRule(id_subject="S0001", entity="currency", kind="sorcery"))


def test_a_rule_can_be_written_read_changed_and_removed_over_the_api(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app import main
    from app.services.supplier_rules import SupplierRuleStore

    monkeypatch.setattr(main, "supplier_rule_store", SupplierRuleStore(tmp_path / "rules.db"))
    with TestClient(main.app) as client:
        created = client.post(
            "/api/supplier-rules",
            json={"id_subject": "S0001", "entity": "currency", "kind": "fixed", "value": "EUR"},
        )
        assert created.status_code == 201, created.text
        rule_id = created.json()["id"]

        assert client.get("/api/supplier-rules?id_subject=S0001").json()[0]["value"] == "EUR"
        assert client.get("/api/supplier-rules?id_subject=S0002").json() == []

        changed = client.patch(f"/api/supplier-rules/{rule_id}", json={"value": "GBP"})
        assert changed.json()["value"] == "GBP"

        assert client.delete(f"/api/supplier-rules/{rule_id}").status_code == 204
        assert client.get("/api/supplier-rules").json() == []


def test_changing_a_rule_that_is_not_there_is_a_404(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from app import main
    from app.services.supplier_rules import SupplierRuleStore

    monkeypatch.setattr(main, "supplier_rule_store", SupplierRuleStore(tmp_path / "rules.db"))
    with TestClient(main.app) as client:
        assert client.patch("/api/supplier-rules/999", json={"value": "x"}).status_code == 404
