"""When the inference runtime dies, a run must stop rather than keep asking."""

import pytest

from app.evaluation.runner import model_is_gone


def test_the_engine_being_unloaded_is_recognised() -> None:
    assert model_is_gone('LM Studio rejected the request: {"error":"Model is unloaded."}')


def test_the_engine_dying_mid_request_is_recognised() -> None:
    assert model_is_gone(
        "LM Studio terminated the request because the model was unloaded, replaced, or "
        "stopped during inference. Wait until the model is ready, then retry."
    )


def test_the_engine_process_being_gone_is_recognised() -> None:
    assert model_is_gone(
        'LM Studio rejected the request: {"error":"Engine protocol predict request failed: '
        'fetch failed"}'
    )
    assert model_is_gone("LM Studio is not reachable")


def test_a_crash_while_reading_the_page_is_recognised() -> None:
    assert model_is_gone(
        "LM Studio stopped while processing the document image, more than once."
    )


def test_an_ordinary_document_failure_is_not_mistaken_for_it() -> None:
    """A bad answer or a missing label says nothing about the runtime."""
    assert not model_is_gone("The response does not contain one named value per entity")
    assert not model_is_gone("Labels name an entity that is not configured: nonexistent")
    assert not model_is_gone(
        "The model reached its output token limit before finishing the JSON object."
    )
    assert not model_is_gone("Document AI refused processor x (403). Permission denied")
