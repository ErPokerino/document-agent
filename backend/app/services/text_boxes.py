"""Where on the page an extracted value came from.

The model is never asked for coordinates. Asking would multiply output tokens
and invite exactly the copying failures a small model already makes — and a
wrong rectangle is worse than none, because it looks authoritative. Document AI
already returns every token with its box, so the value is located in the token
stream instead and the matching boxes are unioned.

Two limits are accepted rather than papered over. A string occurring several
times in a document is ambiguous, and the first occurrence is taken. A value
the OCR never saw cannot be highlighted at all, which includes anything the
model inferred rather than read.

The other difficulty is that the app normalizes before storing: it holds
`2024-03-14` for a page that reads `14/03/2024`, and `1220.00` for one that
reads `1.220,00`. Searching only for the stored spelling would miss the fields
most worth checking, so a value is also looked for under the spellings a
document plausibly used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Enough tokens to cover a long supplier name; beyond that a "value" is not a
# value, and the window would only find coincidences.
MAX_TOKEN_SPAN = 12


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float

    def union(self, other: "Box") -> "Box":
        return Box(
            left=min(self.left, other.left),
            top=min(self.top, other.top),
            right=max(self.right, other.right),
            bottom=max(self.bottom, other.bottom),
        )


@dataclass(frozen=True)
class TextToken:
    text: str
    page: int
    box: Box


@dataclass(frozen=True)
class Located:
    page: int
    box: Box


def tokens_from_ocr(document: dict) -> list[TextToken]:
    """Every token an OCR processor read, with its page and its box.

    Coordinates are the normalized ones — 0 to 1 across the page — so they
    survive whatever size the page is later rendered at.
    """
    full_text: str = document.get("text") or ""
    tokens: list[TextToken] = []

    for page_number, page in enumerate(document.get("pages") or []):
        for token in page.get("tokens") or []:
            layout = token.get("layout") or {}
            box = _box_of(layout)
            if box is None:
                continue
            text = _text_of(layout, full_text)
            if not text.strip():
                continue
            tokens.append(TextToken(text=text, page=page_number, box=box))
    return tokens


def locate_value(value: object, tokens: list[TextToken]) -> Located | None:
    """The box around `value` on the page, or None if it is not there."""
    for candidate in _spellings(value):
        found = _find(candidate, tokens)
        if found is not None:
            return found
    return None


# -- reading one token ---------------------------------------------------------


def _box_of(layout: dict) -> Box | None:
    vertices = ((layout.get("boundingPoly") or {}).get("normalizedVertices")) or []
    xs = [float(vertex.get("x", 0.0)) for vertex in vertices]
    ys = [float(vertex.get("y", 0.0)) for vertex in vertices]
    if not xs or not ys:
        return None
    return Box(left=min(xs), top=min(ys), right=max(xs), bottom=max(ys))


def _text_of(layout: dict, full_text: str) -> str:
    """A token holds offsets into the document text, not the text itself."""
    segments = ((layout.get("textAnchor") or {}).get("textSegments")) or []
    pieces = []
    for segment in segments:
        start = int(segment.get("startIndex") or 0)
        end = int(segment.get("endIndex") or 0)
        pieces.append(full_text[start:end])
    return "".join(pieces)


# -- matching ------------------------------------------------------------------

_NOISE = re.compile(r"[^0-9a-z]+")


def _key(text: str) -> str:
    """What two strings have to share to count as the same words.

    Case, spacing and punctuation all differ between what the model wrote and
    what the page shows — `ACME SUPPLIES LTD.` against `Acme Supplies Ltd` —
    and none of those differences mean it is a different value.
    """
    return _NOISE.sub("", (text or "").casefold())


def _find(value: str, tokens: list[TextToken]) -> Located | None:
    target = _key(value)
    if not target:
        return None

    for start in range(len(tokens)):
        page = tokens[start].page
        joined = ""
        box = tokens[start].box
        for offset in range(MAX_TOKEN_SPAN):
            index = start + offset
            if index >= len(tokens) or tokens[index].page != page:
                break
            joined += _key(tokens[index].text)
            box = box.union(tokens[index].box) if offset else tokens[index].box
            if joined == target:
                return Located(page=page, box=box)
            if not target.startswith(joined):
                break
    return None


# -- the spellings a page might have used --------------------------------------

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DECIMAL = re.compile(r"^-?\d+\.\d+$")


def _spellings(value: object) -> list[str]:
    """The stored value first, then the forms a document plausibly printed.

    Order matters: an exact match is always preferred to a reconstruction.
    """
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []

    candidates = [text]

    date = _ISO_DATE.match(text)
    if date is not None:
        year, month, day = date.groups()
        for separator in ("/", "-", "."):
            candidates.append(f"{day}{separator}{month}{separator}{year}")
            candidates.append(f"{month}{separator}{day}{separator}{year}")
        # Some documents drop the leading zero.
        candidates.append(f"{int(day)}/{int(month)}/{year}")

    if _DECIMAL.match(text):
        whole, _, fraction = text.partition(".")
        # 1220.00 on a page that wrote 1.220,00 — and on one that wrote 1220.
        candidates.append(f"{whole},{fraction}")
        candidates.append(_grouped(whole, ".") + "," + fraction)
        candidates.append(_grouped(whole, ",") + "." + fraction)
        if int(fraction) == 0:
            candidates.append(whole)
            candidates.append(_grouped(whole, "."))
            candidates.append(_grouped(whole, ","))

    # `_key` strips punctuation, so several of those collapse together; keeping
    # the order and dropping repeats keeps the search short.
    return list(dict.fromkeys(candidates))


def _grouped(whole: str, separator: str) -> str:
    sign, digits = ("-", whole[1:]) if whole.startswith("-") else ("", whole)
    parts = []
    while len(digits) > 3:
        parts.insert(0, digits[-3:])
        digits = digits[:-3]
    parts.insert(0, digits)
    return sign + separator.join(parts)
