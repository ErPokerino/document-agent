"""What a field should look like, said once for everyone who asks.

Three readers are told the format of a value: Gemini's response schema, the
Custom Extractor's schema, and a local model through its prompt. Each used to
phrase it for itself, and the drift is not hypothetical — the same Custom
Extractor answered `$` for a currency given no description and `USD` when told
the code was ISO 4217.

So the sentence lives here, and the format instruction rides behind whatever
was written about the field in Extraction, which is the part a person meant.

It rides behind it **only when the description does not already say it**. That
is not tidiness: a description reading "Normalize it to YYYY-MM-DD" followed by
"Format the value as YYYY-MM-DD" made the Custom Extractor return no date at
all, every time, while either sentence alone worked every time. Repeating an
instruction to a generative reader is not free.
"""

from app.domain.models import EntityDefinition, EntityFormat


FORMAT_RIDERS = {
    EntityFormat.date: "Format the value as YYYY-MM-DD.",
    EntityFormat.currency: (
        "Give the three-letter ISO 4217 code in upper case, such as EUR, USD or GBP — "
        "never a currency symbol."
    ),
    EntityFormat.decimal: (
        "Give a plain decimal number, with a full stop for the decimal point and no "
        "thousands separator or currency symbol."
    ),
    EntityFormat.integer: "Give a whole number, with no thousands separator.",
}

# What a description has to contain for its format to count as already stated.
# Deliberately the distinctive token rather than a whole phrase: someone will
# write "as YYYY-MM-DD" or "in YYYY-MM-DD format", and both mean the rider
# would be a repetition.
ALREADY_SAID = {
    EntityFormat.date: ("yyyy-mm-dd",),
    EntityFormat.currency: ("iso 4217", "iso4217"),
    EntityFormat.decimal: ("thousands separator", "thousand separator", "decimal point"),
    EntityFormat.integer: ("thousands separator", "thousand separator", "whole number"),
}


# What to say to a reader that points at a span on the page rather than writing
# a value of its own. It cannot obey "never a symbol" when the page shows only a
# symbol — and an instruction a field cannot satisfy is not merely ignored: the
# Custom Extractor returned nothing for that field *and* dropped the date from
# the same response. So a page reader is hinted at, never forbidden, and the
# app's own validation does the converting afterwards.
PAGE_READER_RIDERS = {
    EntityFormat.date: "Format the value as YYYY-MM-DD.",
    EntityFormat.currency: "Give the ISO 4217 code when the document states one.",
    EntityFormat.decimal: "",
    EntityFormat.integer: "",
}


def described_for_reader(entity: EntityDefinition, reads_from_page: bool = False) -> str:
    """The field's description, with what its format requires if it is missing.

    `reads_from_page` is for a reader that can only point at what is printed —
    Google's Custom Extractor — as against one that writes the value itself.
    """
    written = (entity.description or "").strip()
    riders = PAGE_READER_RIDERS if reads_from_page else FORMAT_RIDERS
    rider = riders.get(entity.format, "")
    if not rider:
        return written

    lowered = written.lower()
    if any(marker in lowered for marker in ALREADY_SAID.get(entity.format, ())):
        return written
    return f"{written} {rider}".strip()
