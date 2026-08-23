"""The supplier register: what a derived entity is looked up in."""

import pytest

from app.services.master_data import DuplicateSubject, SubjectStore, UnknownSubject


@pytest.fixture
def store(tmp_path) -> SubjectStore:
    return SubjectStore(tmp_path / "docuflow.db")


def test_a_new_register_is_empty(store) -> None:
    assert store.list() == []


def test_adding_a_supplier_gives_it_an_identifier_and_a_normalized_name(store) -> None:
    subject = store.add("ACME S.r.l.")

    assert subject.id_subject == "S0001"
    assert subject.name == "ACME S.r.l."
    assert subject.normalized_name == "acme"


def test_identifiers_run_in_order_and_are_never_reused(store) -> None:
    store.add("First")
    second = store.add("Second")
    store.delete(second.id_subject)

    assert store.add("Third").id_subject == "S0003"


def test_the_same_supplier_cannot_be_registered_twice(store) -> None:
    store.add("ACME S.r.l.")

    # Same company, written differently: the register must stay one row per
    # supplier, or a lookup has two right answers.
    with pytest.raises(DuplicateSubject, match="ACME"):
        store.add("acme srl")


def test_a_supplier_can_be_corrected(store) -> None:
    subject = store.add("ACME")

    updated = store.update(subject.id_subject, name="ACME International")

    assert updated.name == "ACME International"
    assert updated.normalized_name == "acme international"
    assert store.read(subject.id_subject).name == "ACME International"


def test_renaming_onto_another_supplier_is_refused(store) -> None:
    store.add("ACME")
    other = store.add("Zeta")

    with pytest.raises(DuplicateSubject):
        store.update(other.id_subject, name="acme")


def test_a_deleted_supplier_is_gone(store) -> None:
    subject = store.add("ACME")

    store.delete(subject.id_subject)

    assert store.list() == []
    with pytest.raises(UnknownSubject):
        store.read(subject.id_subject)


def test_acting_on_a_supplier_that_is_not_there_says_so(store) -> None:
    with pytest.raises(UnknownSubject):
        store.delete("S9999")
    with pytest.raises(UnknownSubject):
        store.update("S9999", name="x")


def test_the_register_is_listed_by_name(store) -> None:
    store.add("Zeta")
    store.add("Acme")

    assert [subject.name for subject in store.list()] == ["Acme", "Zeta"]


def test_the_register_can_be_searched_by_either_spelling(store) -> None:
    store.add("ACME S.r.l.")
    store.add("Zeta Trasporti")

    assert [s.name for s in store.list(query="acme")] == ["ACME S.r.l."]
    assert [s.name for s in store.list(query="TRASP")] == ["Zeta Trasporti"]


def test_seeding_adds_the_names_it_is_given_and_skips_the_ones_it_has(store) -> None:
    store.add("ACME S.r.l.")

    added = store.seed(["acme srl", "Zeta Trasporti", "Zeta Trasporti"])

    assert [subject.name for subject in added] == ["Zeta Trasporti"]
    assert len(store.list()) == 2


def test_seeding_never_overwrites_a_spelling_someone_corrected(store) -> None:
    store.add("ACME S.r.l.")

    # Same supplier once normalized, so the row is left exactly as it was.
    store.seed(["acme"])

    assert [subject.name for subject in store.list()] == ["ACME S.r.l."]


def test_two_genuinely_different_names_are_two_suppliers(store) -> None:
    """The register matches exactly; deciding that two names mean the same
    company is the lookup's job, and it is not allowed to guess here."""
    store.add("ACME International")

    store.seed(["ACME"])

    assert len(store.list()) == 2
