"""Which hosted models answer in which location, as last checked.

A model Google refuses stays listed: whether it answers depends on the
project's quota and on the location it is asked in, and both change outside
DocuFlow. A check asks each model for one token, and its result is kept in
this process until the next check of the same model and location.
"""

import re
from datetime import datetime, timezone

from app.domain.settings import HostedModelCheck

_checks: dict[tuple[str, str], HostedModelCheck] = {}

_QUOTA = re.compile(r"Quota exceeded for (\S+?)(?: with base model: ([\w.-]+))?\.(?:\s|$)")


def _first_sentence(message: str) -> str:
    text = " ".join(message.split())
    return (text.split(". ")[0].rstrip(".") + ".")[:300] if text else "no detail."


def refusal_fact(status_code: int, message: str) -> str:
    """Google's refusal as what happened, without the advice it appends."""
    if status_code == 429:
        found = _QUOTA.search(message)
        if found:
            metric = found.group(1).rsplit("/", 1)[-1]
            base = f" for {found.group(2)}" if found.group(2) else ""
            return f"Google refused the request with 429: the project's quota {metric}{base} is used up or zero."
        detail = _first_sentence(message) if message.strip() else ""
        return f"Google refused the request with 429 (rate limit or quota). {detail}".strip()
    if status_code == 404:
        return "Google returned 404: the model is not offered in this location, or this project has no access to it."
    return f"Google returned {status_code}: {_first_sentence(message)}"


def status_of(status_code: int) -> str:
    if status_code < 400:
        return "answering"
    if status_code == 429:
        return "no_quota"
    if status_code == 404:
        return "not_offered"
    return "refused"


def record(model: str, publisher: str, location: str, status_code: int, message: str = "") -> HostedModelCheck:
    check = HostedModelCheck(
        model=model,
        publisher=publisher,
        location=location,
        status=status_of(status_code),  # type: ignore[arg-type]
        detail="" if status_code < 400 else refusal_fact(status_code, message),
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    _checks[(model, location)] = check
    return check


def record_unreachable(model: str, publisher: str, location: str, detail: str) -> HostedModelCheck:
    check = HostedModelCheck(
        model=model, publisher=publisher, location=location, status="refused", detail=detail,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    _checks[(model, location)] = check
    return check


def all_checks() -> list[HostedModelCheck]:
    return sorted(_checks.values(), key=lambda check: (check.publisher, check.model, check.location))


def clear() -> None:
    _checks.clear()
