"""Google Document AI: OCR and the Layout Parser, over plain REST.

Only `google-auth` is used, and only to sign the assertion. Document AI
refuses a self-signed JWT (`ACCESS_TOKEN_TYPE_UNSUPPORTED`), so the assertion
is exchanged for a real access token, which is then cached until it is nearly
expired.

The key is a service account JSON file on disk. Nothing about it is ever sent
to the browser: the settings endpoint reports only which account and project it
belongs to.
"""

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# The exchanged token lasts an hour; renew a minute early so a long run never
# starts a request with a token that expires mid-flight.
TOKEN_MARGIN_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 180

HEADING_TYPES = {
    "title": "#",
    "heading-1": "#",
    "heading-2": "##",
    "heading-3": "###",
    "heading-4": "####",
    "heading-5": "#####",
    "heading-6": "######",
}


class DocumentAiError(RuntimeError):
    """Anything that stops a document from being processed, in plain words."""


@dataclass(frozen=True)
class ServiceAccount:
    client_email: str
    project_id: str
    token_uri: str
    info: dict[str, Any]

    @staticmethod
    def load(path: Path) -> "ServiceAccount":
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DocumentAiError(
                f"No service account key at {path}, which is where DocuFlow reads one."
            ) from exc
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DocumentAiError(
                f"The key file at {path} is not readable JSON."
            ) from exc
        if not isinstance(info, dict) or info.get("type") != "service_account":
            raise DocumentAiError(
                "That file is JSON, but not a service account key: its type is not "
                "'service_account'."
            )
        missing = [
            field for field in ("client_email", "private_key", "token_uri") if not info.get(field)
        ]
        if missing:
            raise DocumentAiError(
                f"The key file is a service account key with no {', '.join(missing)}."
            )
        return ServiceAccount(
            client_email=info["client_email"],
            project_id=info.get("project_id", ""),
            token_uri=info["token_uri"],
            info=info,
        )


def text_from_ocr(document: dict[str, Any]) -> str:
    """The plain text an OCR processor read off the page."""
    return document.get("text") or ""


def _blocks_to_chunks(blocks: list[dict[str, Any]]) -> list[str]:
    """One chunk per block. A table or a list is a single chunk of its own lines."""
    chunks: list[str] = []
    for block in blocks:
        text_block = block.get("textBlock")
        if text_block is not None:
            text = (text_block.get("text") or "").strip()
            prefix = HEADING_TYPES.get(text_block.get("type", ""), "")
            if text:
                chunks.append(f"{prefix} {text}".strip())
            chunks.extend(_blocks_to_chunks(text_block.get("blocks") or []))
            continue

        table = block.get("tableBlock")
        if table is not None:
            rows = _table_to_lines(table)
            if rows:
                chunks.append("\n".join(rows))
            continue

        list_block = block.get("listBlock")
        if list_block is not None:
            entries = [
                f"- {line}"
                for entry in list_block.get("listEntries") or []
                for line in _blocks_to_chunks(entry.get("blocks") or [])
            ]
            if entries:
                chunks.append("\n".join(entries))
    return chunks


def _cell_text(cell: dict[str, Any]) -> str:
    return " ".join(_blocks_to_chunks(cell.get("blocks") or [])).strip()


def _table_to_lines(table: dict[str, Any]) -> list[str]:
    header_rows = table.get("headerRows") or []
    body_rows = table.get("bodyRows") or []
    lines: list[str] = []
    for row in header_rows:
        cells = [_cell_text(cell) for cell in row.get("cells") or []]
        lines.append("| " + " | ".join(cells) + " |")
        lines.append("| " + " | ".join("---" for _ in cells) + " |")
    for row in body_rows:
        cells = [_cell_text(cell) for cell in row.get("cells") or []]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def markdown_from_layout(document_layout: dict[str, Any]) -> str:
    """The layout tree as text a model can read, keeping headings and tables.

    Markdown, because the structure is the whole reason to pay for this
    processor, and it is the shape models are most used to reading.
    """
    return "\n\n".join(_blocks_to_chunks(document_layout.get("blocks") or []))


class DocumentAiClient:
    def __init__(self, credentials_path: Path, project_id: str, location: str) -> None:
        self.credentials_path = Path(credentials_path)
        self.project_id = project_id
        self.location = location
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def host(self) -> str:
        return f"https://{self.location}-documentai.googleapis.com"

    def process_url(self, processor_id: str, version: str = "v1") -> str:
        return (
            f"{self.host}/{version}/projects/{self.project_id}"
            f"/locations/{self.location}/processors/{processor_id}:process"
        )

    def account(self) -> ServiceAccount:
        return ServiceAccount.load(self.credentials_path)

    async def _exchange_assertion(self) -> tuple[str, float]:
        """Sign a JWT with the service account key and trade it for a token."""
        from google.auth import crypt, jwt

        account = self.account()
        try:
            signer = crypt.RSASigner.from_service_account_info(account.info)
        except (ValueError, TypeError) as exc:
            raise DocumentAiError(f"The private key in the key file is unusable: {exc}") from exc

        issued = int(time.time())
        assertion = jwt.encode(
            signer,
            {
                "iss": account.client_email,
                "scope": SCOPE,
                "aud": account.token_uri,
                "iat": issued,
                "exp": issued + 3600,
            },
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    account.token_uri,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion.decode("ascii")
                        if isinstance(assertion, bytes)
                        else assertion,
                    },
                )
        except httpx.HTTPError as exc:
            raise DocumentAiError(f"Google's token endpoint is not reachable: {exc}") from exc

        if response.status_code != 200:
            raise DocumentAiError(
                f"Google refused the service account key ({response.status_code}). "
                f"{_google_message(response)}"
            )
        payload = response.json()
        return payload["access_token"], time.time() + float(payload.get("expires_in", 3600))

    async def _access_token(self) -> str:
        if self._token is not None and time.time() < self._token_expires_at - TOKEN_MARGIN_SECONDS:
            return self._token
        self._token, self._token_expires_at = await self._exchange_assertion()
        return self._token

    async def process(
        self,
        processor_id: str,
        content: bytes,
        process_options: dict[str, Any] | None = None,
        version: str = "v1",
    ) -> dict[str, Any]:
        """Run one processor over one document and return the raw answer.

        `process_options` is how a generative Custom Extractor is told which
        fields to look for, per request, instead of by editing its schema.
        """
        if not processor_id.strip():
            raise DocumentAiError("No processor id is configured for this step.")
        if not self.project_id.strip():
            raise DocumentAiError("No Google Cloud project is configured in Settings.")

        payload: dict[str, Any] = {
            "rawDocument": {
                "content": base64.b64encode(content).decode("ascii"),
                "mimeType": "application/pdf",
            }
        }
        if process_options:
            payload["processOptions"] = process_options
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    self.process_url(processor_id, version),
                    json=payload,
                    headers={"Authorization": f"Bearer {await self._access_token()}"},
                )
        except httpx.HTTPError as exc:
            raise DocumentAiError(f"Document AI is not reachable: {exc}") from exc

        if response.status_code != 200:
            raise DocumentAiError(
                f"Document AI refused processor {processor_id} "
                f"({response.status_code}). {_google_message(response)}"
            )
        return response.json()


def _google_message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", {}).get("message", "")).strip()
    except ValueError:
        return response.text[:200]
