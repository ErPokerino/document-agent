"""Matching a supplier name against an internal register."""

import pytest

from app.services.similarity import ALGORITHMS, normalize_company_name, similarity


def test_a_name_is_normalized_down_to_what_identifies_it() -> None:
    assert normalize_company_name("  ACME  S.r.l. ") == "acme"
    assert normalize_company_name("UL VS LTD") == "ul vs"
    assert normalize_company_name("Rossi & Figli S.p.A.") == "rossi figli"
    assert normalize_company_name("MÜLLER GmbH") == "muller"


def test_normalizing_never_throws_the_whole_name_away() -> None:
    # A name that is only a legal form keeps it, or nothing would be left.
    assert normalize_company_name("S.R.L.") == "srl"
    assert normalize_company_name("") == ""


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_the_same_name_always_scores_one(algorithm: str) -> None:
    assert similarity("ACME S.r.l.", "acme", algorithm) == 1.0


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_two_unrelated_names_score_near_zero(algorithm: str) -> None:
    assert similarity("Acme Ltd", "Zeta Trasporti", algorithm) < 0.25


def test_word_order_does_not_matter_to_the_token_algorithm() -> None:
    assert similarity("Rossi Trasporti", "Trasporti Rossi", "token_set") == 1.0


def test_a_typo_is_forgiven_by_the_character_algorithm() -> None:
    # OCR reading "Anthropic" as "Anthropio" must still find the register row.
    assert similarity("Anthropio", "Anthropic", "trigram") > 0.7
    assert similarity("Anthropio", "Anthropic", "token_set") == 0.0


def test_the_combined_algorithm_takes_whichever_signal_is_stronger() -> None:
    assert similarity("Anthropio", "Anthropic", "combined") == similarity(
        "Anthropio", "Anthropic", "trigram"
    )
    assert similarity("Trasporti Rossi", "Rossi Trasporti", "combined") == 1.0


def test_a_missing_side_scores_zero_rather_than_failing() -> None:
    for algorithm in ALGORITHMS:
        assert similarity("", "Acme", algorithm) == 0.0
        assert similarity("Acme", "", algorithm) == 0.0


def test_an_unknown_algorithm_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="algorithm"):
        similarity("a", "b", "telepathy")


def test_a_partial_name_scores_between_the_extremes() -> None:
    score = similarity("UL VS LTD", "UL Solutions", "combined")

    assert 0.2 < score < 0.8
