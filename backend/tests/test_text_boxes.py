"""Finding where on the page an extracted value came from.

The model is never asked for coordinates. Document AI already returns every
token with its box, so once the model answers `supplier_name: "ACME SUPPLIES
LTD"` that string is located in the token stream and the matching boxes are
unioned. Deterministic, free, and it fails by finding nothing rather than by
inventing a rectangle.

Two limits are accepted on purpose: a string occurring several times is
ambiguous and the first occurrence wins, and a value the OCR never saw cannot
be highlighted at all.
"""

import pytest

from app.services.text_boxes import Box, locate_value, tokens_from_ocr


def token(text: str, start: int, left: float, top: float, page: int = 0) -> dict:
    """One Document AI token, in the shape the API actually returns."""
    return {
        "layout": {
            "textAnchor": {"textSegments": [{"startIndex": str(start), "endIndex": str(start + len(text))}]},
            "boundingPoly": {
                "normalizedVertices": [
                    {"x": left, "y": top},
                    {"x": left + 0.08, "y": top},
                    {"x": left + 0.08, "y": top + 0.02},
                    {"x": left, "y": top + 0.02},
                ]
            },
        }
    }


def ocr_document(text: str, tokens_by_page: list[list[dict]]) -> dict:
    return {"text": text, "pages": [{"tokens": tokens} for tokens in tokens_by_page]}


PAGE_TEXT = "INVOICE\nACME SUPPLIES LTD\nNo. INV-2024-0042\nDate 14/03/2024\nTotal 1.220,00 EUR\n"


def sample() -> dict:
    """One page, laid out the way the words sit on it."""
    words = []
    cursor = 0
    placed: list[dict] = []
    row = 0.0
    for line in PAGE_TEXT.split("\n"):
        column = 0.1
        for word in line.split():
            start = PAGE_TEXT.index(word, cursor)
            placed.append(token(word, start, column, row))
            cursor = start + len(word)
            column += 0.1
        row += 0.1
    return ocr_document(PAGE_TEXT, [placed])


# -- reading the tokens --------------------------------------------------------


def test_every_token_arrives_with_its_text_and_its_box() -> None:
    tokens = tokens_from_ocr(sample())
    assert [t.text for t in tokens][:3] == ["INVOICE", "ACME", "SUPPLIES"]
    first = tokens[0]
    assert first.page == 0
    assert 0 <= first.box.left < first.box.right <= 1
    assert 0 <= first.box.top < first.box.bottom <= 1


def test_a_response_without_pages_yields_nothing_rather_than_failing() -> None:
    assert tokens_from_ocr({}) == []
    assert tokens_from_ocr({"text": "x", "pages": []}) == []


def test_a_token_with_no_box_is_skipped() -> None:
    broken = {"layout": {"textAnchor": {"textSegments": [{"startIndex": "0", "endIndex": "3"}]}}}
    assert tokens_from_ocr(ocr_document("abc", [[broken]])) == []


# -- locating a value ----------------------------------------------------------


def test_a_value_spanning_several_words_gets_one_box_around_them_all() -> None:
    found = locate_value("ACME SUPPLIES LTD", tokens_from_ocr(sample()))
    assert found is not None
    assert found.page == 0
    # Wider than any single token, because it covers three of them.
    assert found.box.right - found.box.left > 0.08


def test_case_and_spacing_do_not_prevent_a_match() -> None:
    tokens = tokens_from_ocr(sample())
    assert locate_value("acme   supplies ltd", tokens) is not None
    assert locate_value("Acme Supplies Ltd", tokens) is not None


def test_a_value_the_page_never_showed_is_not_given_a_box() -> None:
    """Failing to find is the correct answer, and better than a wrong rectangle."""
    assert locate_value("GLOBEX CORPORATION", tokens_from_ocr(sample())) is None
    assert locate_value("", tokens_from_ocr(sample())) is None
    assert locate_value(None, tokens_from_ocr(sample())) is None


def test_punctuation_around_a_word_does_not_hide_it() -> None:
    assert locate_value("INV-2024-0042", tokens_from_ocr(sample())) is not None


# -- values the app normalized before storing them ------------------------------


def test_a_date_is_found_under_the_spelling_the_page_used() -> None:
    """The app stores 2024-03-14; the invoice says 14/03/2024."""
    found = locate_value("2024-03-14", tokens_from_ocr(sample()))
    assert found is not None


def test_a_date_written_the_other_way_round_is_also_found() -> None:
    document = ocr_document("Date 03/14/2024\n", [[token("03/14/2024", 5, 0.2, 0.1)]])
    assert locate_value("2024-03-14", tokens_from_ocr(document)) is not None


def test_an_amount_is_found_under_european_punctuation() -> None:
    """The app stores 1220.00; the invoice says 1.220,00."""
    found = locate_value("1220.00", tokens_from_ocr(sample()))
    assert found is not None


def test_a_whole_amount_matches_a_page_that_wrote_no_decimals() -> None:
    document = ocr_document("Total 1220 EUR\n", [[token("1220", 6, 0.2, 0.1)]])
    assert locate_value("1220.00", tokens_from_ocr(document)) is not None


def test_a_number_that_is_simply_absent_is_still_not_invented() -> None:
    assert locate_value("9999.99", tokens_from_ocr(sample())) is None


# -- several pages, several occurrences -----------------------------------------


def test_the_page_a_value_was_found_on_is_reported() -> None:
    document = ocr_document(
        "first\nACME LTD\n",
        [[token("first", 0, 0.1, 0.1)], [token("ACME", 6, 0.1, 0.2), token("LTD", 11, 0.2, 0.2)]],
    )
    found = locate_value("ACME LTD", tokens_from_ocr(document))
    assert found is not None and found.page == 1


def test_a_repeated_value_takes_the_first_occurrence() -> None:
    """Ambiguous by nature. Accepted: the first is shown, not a guess between them."""
    document = ocr_document(
        "TOTAL 50 TOTAL 50\n",
        [[
            token("TOTAL", 0, 0.1, 0.1), token("50", 6, 0.2, 0.1),
            token("TOTAL", 9, 0.1, 0.5), token("50", 15, 0.2, 0.5),
        ]],
    )
    found = locate_value("TOTAL 50", tokens_from_ocr(document))
    assert found is not None
    assert found.box.top < 0.4


def test_a_match_never_spans_two_pages() -> None:
    document = ocr_document(
        "ACME\nLTD\n",
        [[token("ACME", 0, 0.1, 0.1)], [token("LTD", 5, 0.1, 0.1)]],
    )
    assert locate_value("ACME LTD", tokens_from_ocr(document)) is None


def test_a_box_is_the_union_and_stays_inside_the_page() -> None:
    document = ocr_document(
        "ACME LTD\n",
        [[token("ACME", 0, 0.10, 0.20), token("LTD", 5, 0.30, 0.22)]],
    )
    found = locate_value("ACME LTD", tokens_from_ocr(document))
    assert isinstance(found.box, Box)
    assert found.box.left == pytest.approx(0.10)
    assert found.box.right == pytest.approx(0.38)
    assert found.box.top == pytest.approx(0.20)
    assert found.box.bottom == pytest.approx(0.24)


# -- wired into a result -------------------------------------------------------


def test_only_the_fields_the_page_showed_get_a_location() -> None:
    from app.domain.models import FieldExtraction
    from app.main import _field_locations

    artifacts = {
        "ocr_tokens": tokens_from_ocr(sample()),
        "extraction": {
            "supplier_name": FieldExtraction(value="ACME SUPPLIES LTD", confidence="high"),
            "date": FieldExtraction(value="2024-03-14", confidence="high"),
            "id_subject": FieldExtraction(value="S0007", confidence="high"),
            "missing": FieldExtraction(value=None, confidence="low"),
        },
    }
    located = {location.entity for location in _field_locations(artifacts)}
    assert located == {"supplier_name", "date"}
    # id_subject is derived from a register and was never printed; a null value
    # was never read either. Neither is given a rectangle.


def test_a_pipeline_that_never_read_the_page_locates_nothing() -> None:
    from app.domain.models import FieldExtraction
    from app.main import _field_locations

    artifacts = {"extraction": {"supplier_name": FieldExtraction(value="ACME", confidence="high")}}
    assert _field_locations(artifacts) == []
