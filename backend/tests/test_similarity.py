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


@pytest.mark.parametrize("algorithm", [a for a in ALGORITHMS if a != "jaro_winkler"])
def test_two_unrelated_names_score_near_zero(algorithm: str) -> None:
    assert similarity("Acme Ltd", "Zeta Trasporti", algorithm) < 0.45


def test_jaro_winkler_never_scores_two_names_near_zero() -> None:
    """Worth knowing before picking it, and before picking a threshold.

    Jaro-Winkler counts any character that appears within a window, so two
    unrelated names still share vowels and land around 0.4. It measures
    "how alike", not "how likely the same", and combined inherits that floor.
    """
    unrelated = similarity("Acme Ltd", "Zeta Trasporti", "jaro_winkler")

    assert 0.3 < unrelated < 0.5
    assert similarity("Acme Ltd", "Zeta Trasporti", "combined") == unrelated


def test_word_order_does_not_matter_to_the_token_algorithm() -> None:
    assert similarity("Rossi Trasporti", "Trasporti Rossi", "token_set") == 1.0


def test_a_typo_is_forgiven_by_the_character_algorithm() -> None:
    # OCR reading "Anthropic" as "Anthropio" must still find the register row.
    assert similarity("Anthropio", "Anthropic", "trigram") > 0.7
    assert similarity("Anthropio", "Anthropic", "token_set") == 0.0


def test_the_combined_algorithm_takes_whichever_signal_is_stronger() -> None:
    assert similarity("Trasporti Rossi", "Rossi Trasporti", "combined") == 1.0
    assert similarity("Anthropio", "Anthropic", "combined") > similarity(
        "Anthropio", "Anthropic", "token_set"
    )


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


def test_exact_is_all_or_nothing_on_the_normalized_name() -> None:
    assert similarity("ACME S.r.l.", "acme", "exact") == 1.0
    assert similarity("ACME", "ACME International", "exact") == 0.0
    assert similarity("Anthropio", "Anthropic", "exact") == 0.0


def test_edit_distance_counts_the_changes_it_would_take() -> None:
    # One substitution in nine characters.
    assert similarity("Anthropio", "Anthropic", "levenshtein") == pytest.approx(8 / 9)
    assert similarity("abc", "xyz", "levenshtein") == 0.0


def test_jaro_winkler_rewards_a_name_that_starts_the_same() -> None:
    shared_prefix = similarity("Martini Group", "Martini Grupo", "jaro_winkler")
    shared_suffix = similarity("Group Martini", "Grupo Martini", "jaro_winkler")

    assert shared_prefix > shared_suffix
    assert similarity("Anthropic", "Anthropic", "jaro_winkler") == 1.0


def test_jaro_winkler_forgives_two_letters_swapped() -> None:
    # A transposition is the typo an edit distance punishes hardest.
    assert similarity("Recanti", "Recnati", "jaro_winkler") > 0.9


def test_the_combined_algorithm_is_the_best_of_the_others() -> None:
    pair = ("UL VS LTD", "UL Solutions")
    others = [similarity(*pair, name) for name in ALGORITHMS if name != "combined"]

    assert similarity(*pair, "combined") == max(others)


def test_every_algorithm_stays_inside_the_zero_to_one_range() -> None:
    pairs = [("Acme", "Acme"), ("Acme", "Zeta"), ("A", "Anthropic Ltd"), ("Rossi & Figli", "Rossi")]

    for algorithm in ALGORITHMS:
        for left, right in pairs:
            assert 0.0 <= similarity(left, right, algorithm) <= 1.0
