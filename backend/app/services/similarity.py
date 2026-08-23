"""Matching a name read off a document against a name in a register.

Two cheap algorithms, because the two ways a supplier name goes wrong are
different problems. Words move around and get dropped — "Rossi Trasporti" for
"Trasporti Rossi S.r.l." — which a set of words handles and a character measure
does not. And OCR misreads letters — "Anthropio" for "Anthropic" — which
character n-grams handle and a set of words does not. `combined` takes whichever
signal is stronger, so one kind of noise cannot hide a match the other kind
would have found.

Deliberately not semantic: an embedding model would say "Trasporti Rossi" and
"Autotrasporti Bianchi" are alike, which is exactly the wrong answer here. That
is a later addition for cases these cannot reach, not a replacement.
"""

import re
import unicodedata

ALGORITHMS = ("combined", "token_set", "trigram")
DEFAULT_ALGORITHM = "combined"

# Legal forms carry no identity: every second Italian supplier is an S.r.l.
LEGAL_FORMS = {
    "srl", "srls", "spa", "sas", "snc", "sapa", "scarl", "soc", "societa",
    "ltd", "limited", "llc", "lp", "llp", "inc", "incorporated", "corp",
    "corporation", "co", "company", "plc", "gmbh", "mbh", "ag", "kg", "ohg",
    "bv", "nv", "sa", "sarl", "sl", "ab", "as", "oy", "aps", "kft", "doo",
    "pty", "pte",
}
TRIGRAM_SIZE = 3


def normalize_company_name(name: str | None) -> str:
    """The part of a name that identifies the company, lower case.

    Accents folded, punctuation dropped, legal forms removed. If removing them
    would leave nothing, they stay: "S.r.l." on its own is all we have.
    """
    if not name:
        return ""
    folded = unicodedata.normalize("NFKD", str(name))
    ascii_only = "".join(char for char in folded if not unicodedata.combining(char))
    # Dots close up rather than split, so "S.r.l." becomes one word to
    # recognise as a legal form instead of three meaningless letters.
    joined = ascii_only.replace(".", "")
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", joined).strip().lower()
    words = cleaned.split()
    meaningful = [word for word in words if word not in LEGAL_FORMS]
    return " ".join(meaningful or words)


def _dice(left: set, right: set) -> float:
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / (len(left) + len(right))


def token_set_similarity(left: str, right: str) -> float:
    """How much of the two word sets is shared, ignoring order and repeats."""
    return _dice(set(left.split()), set(right.split()))


def _trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[index : index + TRIGRAM_SIZE] for index in range(len(padded) - TRIGRAM_SIZE + 1)}


def trigram_similarity(left: str, right: str) -> float:
    """How much of the two letter-triple sets is shared: survives typos."""
    return _dice(_trigrams(left), _trigrams(right))


def similarity(left: str | None, right: str | None, algorithm: str = DEFAULT_ALGORITHM) -> float:
    """A score from 0 to 1 for two company names, after normalizing both."""
    if algorithm not in ALGORITHMS:
        raise ValueError(
            f"Unknown similarity algorithm {algorithm!r}. Use one of: {', '.join(ALGORITHMS)}"
        )
    first = normalize_company_name(left)
    second = normalize_company_name(right)
    if not first or not second:
        return 0.0
    if algorithm == "token_set":
        return token_set_similarity(first, second)
    if algorithm == "trigram":
        return trigram_similarity(first, second)
    return max(token_set_similarity(first, second), trigram_similarity(first, second))
