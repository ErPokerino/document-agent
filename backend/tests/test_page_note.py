"""What the model is told about how much of the document it can see."""

from app.services.lm_studio import page_note


def test_a_whole_document_says_so_with_the_number() -> None:
    note = page_note(total_pages=3, processed_pages=3)

    assert "3 pages" in note
    assert "all 3" in note


def test_a_single_page_document_is_not_described_in_the_plural() -> None:
    note = page_note(total_pages=1, processed_pages=1)

    assert note == "This document has 1 page, and it is supplied here."


def test_a_cut_document_states_both_numbers_and_what_they_mean() -> None:
    note = page_note(total_pages=7, processed_pages=2)

    # The model must know the document is longer than what it was handed, or
    # it reads a subtotal as the total.
    assert "7 pages" in note
    assert "first 2" in note
    assert "5" in note  # the ones it cannot see
    assert "subtotal" in note.lower()


def test_a_cut_to_one_page_reads_as_one_page() -> None:
    note = page_note(total_pages=4, processed_pages=1)

    assert "first page only" in note
    assert "4 pages" in note
