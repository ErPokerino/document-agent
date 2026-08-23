"""Matching a name read off a document against a name in a register.

Every algorithm here first normalizes both sides — accents folded, punctuation
dropped, legal forms removed — and then scores what is left from 0 to 1. They
differ in what kind of difference they forgive, and the ways a supplier name
goes wrong are genuinely different problems:

- `exact`: the normalized names are the same string, or they are not. No
  tolerance at all, which is what you want when the register is authoritative
  and a near miss should be looked at by a person.
- `token_set`: Sørensen–Dice over the sets of words. Order and repeats do not
  matter, and a dropped word costs proportionally. Handles "Rossi Trasporti"
  against "Trasporti Rossi S.r.l."; blind to a typo inside a word.
- `trigram`: Sørensen–Dice over the sets of three-letter sequences, padded at
  the ends. Handles a misread letter, and still sees a word that moved because
  its trigrams are unchanged. Blind to nothing in particular, weak on short
  names where few trigrams exist.
- `levenshtein`: 1 minus the edit distance over the length of the longer name.
  Counts the single-character insertions, deletions and substitutions it would
  take to turn one into the other, so it is the strictest measure of "almost
  the same text". Punishes a swapped pair of letters twice.
- `jaro_winkler`: the classic name-matching measure. It counts characters that
  match within a window and halves the penalty for transpositions, then adds a
  bonus for a shared prefix, because names that begin alike usually are alike.
  Best on short names and OCR transpositions; too forgiving on long ones.
- `combined`: the highest score any of the above gives. One kind of noise
  cannot then hide a match another kind would have found.

Deliberately not semantic: an embedding model would say "Trasporti Rossi" and
"Autotrasporti Bianchi" are alike, which is exactly the wrong answer here. That
is a later addition for cases these cannot reach, not a replacement.
"""

import re
import unicodedata

ALGORITHMS = ("combined", "exact", "token_set", "trigram", "levenshtein", "jaro_winkler")
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


def levenshtein_similarity(left: str, right: str) -> float:
    """1 minus the edit distance, over the length of the longer name."""
    if left == right:
        return 1.0
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return 1 - previous[-1] / max(len(left), len(right))


def jaro_similarity(left: str, right: str) -> float:
    """Matching characters within a window, with transpositions half-priced."""
    if left == right:
        return 1.0
    window = max(len(left), len(right)) // 2 - 1
    if window < 0:
        window = 0

    left_matched = [False] * len(left)
    right_matched = [False] * len(right)
    matches = 0
    for index, char in enumerate(left):
        start = max(0, index - window)
        end = min(index + window + 1, len(right))
        for other in range(start, end):
            if right_matched[other] or right[other] != char:
                continue
            left_matched[index] = right_matched[other] = True
            matches += 1
            break
    if matches == 0:
        return 0.0

    transpositions = 0
    other = 0
    for index, matched in enumerate(left_matched):
        if not matched:
            continue
        while not right_matched[other]:
            other += 1
        if left[index] != right[other]:
            transpositions += 1
        other += 1

    half = transpositions / 2
    return (matches / len(left) + matches / len(right) + (matches - half) / matches) / 3


def jaro_winkler_similarity(left: str, right: str, scale: float = 0.1) -> float:
    """Jaro, plus a bonus of up to four characters of shared prefix."""
    jaro = jaro_similarity(left, right)
    prefix = 0
    for left_char, right_char in zip(left[:4], right[:4]):
        if left_char != right_char:
            break
        prefix += 1
    return jaro + prefix * scale * (1 - jaro)


_MEASURES = {
    "exact": lambda left, right: 1.0 if left == right else 0.0,
    "token_set": token_set_similarity,
    "trigram": trigram_similarity,
    "levenshtein": levenshtein_similarity,
    "jaro_winkler": jaro_winkler_similarity,
}


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
    if algorithm == "combined":
        return max(measure(first, second) for measure in _MEASURES.values())
    return _MEASURES[algorithm](first, second)
