"""The identity Google Cloud gives a running container, with no key file.

On Cloud Run (and Compute Engine, GKE, Cloud Functions) the platform answers on
a metadata server with tokens for the service account the workload runs as.
Asking it there instead of signing with a downloaded key is what lets a
deployment hold no long-lived secret at all. Google-specific by nature, so it
lives in this one adapter and is used only when configured
(`DOCUFLOW_GCP_RUNTIME_IDENTITY`, or a model server behind Google sign-in).
"""

import time

import httpx

from app.services.errors import ProviderError

METADATA = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
HEADERS = {"Metadata-Flavor": "Google"}
# Renewed a minute before it lapses, as the key-file path does.
MARGIN_SECONDS = 60
# Identity tokens last an hour; one is reused for most of that.
ID_TOKEN_SECONDS = 50 * 60

_access: tuple[str, float] | None = None
_identity: dict[str, tuple[str, float]] = {}


class RuntimeIdentityError(ProviderError):
    pass


async def _get(path: str, params: dict[str, str] | None = None) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{METADATA}/{path}", params=params, headers=HEADERS)
    except httpx.HTTPError as exc:
        raise RuntimeIdentityError(
            "The Google Cloud metadata server is not reachable, so this process has no runtime identity. "
            "It answers only inside Google Cloud."
        ) from exc
    if response.status_code != 200:
        raise RuntimeIdentityError(
            f"The Google Cloud metadata server refused a token ({response.status_code}): {response.text[:200]}"
        )
    return response


async def access_token() -> str:
    """An OAuth access token for Google APIs, as the workload's service account."""
    global _access
    if _access is not None and time.time() < _access[1] - MARGIN_SECONDS:
        return _access[0]
    payload = (await _get("token")).json()
    _access = (payload["access_token"], time.time() + float(payload.get("expires_in", 3600)))
    return _access[0]


async def identity_token(audience: str) -> str:
    """A signed identity token for calling a private service at `audience`."""
    cached = _identity.get(audience)
    if cached is not None and time.time() < cached[1] - MARGIN_SECONDS:
        return cached[0]
    token = (await _get("identity", {"audience": audience})).text.strip()
    _identity[audience] = (token, time.time() + ID_TOKEN_SECONDS)
    return token


async def service_account_email() -> str:
    return (await _get("email")).text.strip()
