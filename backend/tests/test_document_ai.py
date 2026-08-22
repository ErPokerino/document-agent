import json
import time

import pytest

from app.services.document_ai import (
    DocumentAiClient,
    DocumentAiError,
    ServiceAccount,
    markdown_from_layout,
    text_from_ocr,
)


def service_account_file(tmp_path, **overrides):
    path = tmp_path / "gcp-service-account.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "a-project",
                "client_email": "docuflow@a-project.iam.gserviceaccount.com",
                "token_uri": "https://oauth2.googleapis.com/token",
                "private_key": "-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----\n",
                **overrides,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_key_file_says_which_account_and_project_it_is_for(tmp_path) -> None:
    account = ServiceAccount.load(service_account_file(tmp_path))

    assert account.client_email == "docuflow@a-project.iam.gserviceaccount.com"
    assert account.project_id == "a-project"


def test_a_missing_key_file_is_reported_in_words_someone_can_act_on(tmp_path) -> None:
    with pytest.raises(DocumentAiError, match="gcp-service-account.json"):
        ServiceAccount.load(tmp_path / "gcp-service-account.json")


def test_a_file_that_is_not_a_service_account_key_is_refused(tmp_path) -> None:
    path = tmp_path / "gcp-service-account.json"
    path.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")

    with pytest.raises(DocumentAiError, match="service account"):
        ServiceAccount.load(path)


def test_a_file_that_is_not_json_at_all_is_refused(tmp_path) -> None:
    path = tmp_path / "gcp-service-account.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(DocumentAiError, match="not readable"):
        ServiceAccount.load(path)


def test_the_ocr_answer_is_the_document_text() -> None:
    assert text_from_ocr({"text": "ACME LTD\nInvoice 7\n"}) == "ACME LTD\nInvoice 7\n"


def test_an_ocr_answer_with_no_text_is_empty_rather_than_missing() -> None:
    assert text_from_ocr({}) == ""


def test_the_layout_becomes_text_that_keeps_the_structure() -> None:
    layout = {
        "blocks": [
            {
                "textBlock": {
                    "text": "ACME LTD",
                    "type": "heading-1",
                    "blocks": [
                        {"textBlock": {"text": "Invoice FE02", "type": "paragraph"}},
                    ],
                }
            }
        ]
    }

    # Headings become headings: the shape is the reason to pay for this parser.
    assert markdown_from_layout(layout) == "# ACME LTD\n\nInvoice FE02"


def test_a_table_keeps_its_rows_and_columns() -> None:
    layout = {
        "blocks": [
            {
                "tableBlock": {
                    "headerRows": [
                        {"cells": [
                            {"blocks": [{"textBlock": {"text": "Item", "type": "paragraph"}}]},
                            {"blocks": [{"textBlock": {"text": "Total", "type": "paragraph"}}]},
                        ]}
                    ],
                    "bodyRows": [
                        {"cells": [
                            {"blocks": [{"textBlock": {"text": "Widget", "type": "paragraph"}}]},
                            {"blocks": [{"textBlock": {"text": "125.31", "type": "paragraph"}}]},
                        ]}
                    ],
                }
            }
        ]
    }

    assert markdown_from_layout(layout) == (
        "| Item | Total |\n| --- | --- |\n| Widget | 125.31 |"
    )


def test_a_list_keeps_its_entries() -> None:
    layout = {
        "blocks": [
            {
                "listBlock": {
                    "listEntries": [
                        {"blocks": [{"textBlock": {"text": "First", "type": "paragraph"}}]},
                        {"blocks": [{"textBlock": {"text": "Second", "type": "paragraph"}}]},
                    ]
                }
            }
        ]
    }

    assert markdown_from_layout(layout) == "- First\n- Second"


def test_an_empty_layout_is_empty_text() -> None:
    assert markdown_from_layout({}) == ""


@pytest.mark.asyncio
async def test_a_token_is_reused_until_it_is_nearly_expired(tmp_path, monkeypatch) -> None:
    client = DocumentAiClient(service_account_file(tmp_path), "a-project", "eu")
    exchanges: list[str] = []

    async def fake_exchange(self):
        exchanges.append("called")
        return "token-" + str(len(exchanges)), time.time() + 3600

    monkeypatch.setattr(DocumentAiClient, "_exchange_assertion", fake_exchange)

    assert await client._access_token() == "token-1"
    assert await client._access_token() == "token-1"

    client._token_expires_at = time.time() + 10
    assert await client._access_token() == "token-2"


def test_the_endpoint_is_built_from_the_region(tmp_path) -> None:
    client = DocumentAiClient(service_account_file(tmp_path), "a-project", "eu")

    assert client.process_url("262c") == (
        "https://eu-documentai.googleapis.com/v1/projects/a-project/locations/eu/processors/262c:process"
    )
