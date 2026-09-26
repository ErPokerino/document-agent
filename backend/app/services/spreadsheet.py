"""CSV as spreadsheets actually write and read it.

Both directions meet Excel. On the way out, a cell that begins with `=`, `+`,
`-` or `@` is read as a formula, and a supplier name or an extracted value is
text somebody else wrote. On the way in, an Italian Excel saves a "CSV" with
semicolons, in Windows-1252 unless told otherwise.
"""

import csv
from urllib.parse import quote

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
DELIMITERS = ",;\t"


def safe_text(value: str) -> str:
    """Text that a spreadsheet shows as text rather than evaluates.

    Only text is guarded: a number keeps its sign, because `-12.5` read as a
    number is exactly what it is.
    """
    if value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def unguarded(value: str) -> str:
    """The text `safe_text` guarded, so an exported file imports unchanged."""
    if value.startswith("'") and value[1:].startswith(FORMULA_PREFIXES):
        return value[1:]
    return value


def decode(content: bytes) -> str:
    """UTF-8 when the file is UTF-8, and Windows-1252 when it is not.

    Every byte decodes in Windows-1252 except five unassigned ones, so a file
    that fails both is not text.
    """
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


def dialect_of(text: str) -> type[csv.Dialect] | csv.Dialect:
    """The delimiter the header row uses, or a comma when it cannot tell."""
    header = text.splitlines()[0] if text else ""
    try:
        return csv.Sniffer().sniff(header, delimiters=DELIMITERS)
    except csv.Error:
        return csv.excel


def content_disposition(kind: str, filename: str) -> str:
    """A download header that survives a name outside Latin-1.

    HTTP headers are Latin-1, so `Fattura_n°3.pdf` fits and `Łódź.zip` does
    not: it failed the response. The plain `filename` is an ASCII stand-in,
    and `filename*` carries the real name for every browser that reads it.
    """
    fallback = "".join(
        character if character.isascii() and character not in '"\\' else "_"
        for character in filename
    )
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
